"""Use cases for domain search operations."""

from __future__ import annotations

import math
import time
from typing import List, Optional

import concurrent.futures

from domain_finder.application.dto import DomainSearchRequest, DomainSearchResult
from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import DomainCandidate, DomainSearchParams, ProviderConfig
from domain_finder.domain.ports import DomainCheckerPort, DomainProviderPort, ResultRepositoryPort
from domain_finder.domain.services import DomainCheckService, DomainGeneratorService
from domain_finder.infrastructure.cache import CacheManager
from domain_finder.infrastructure.persistence import ResultWriter


class RunDomainSearchUseCase:
    """Use case for running domain search with generation and checking."""

    def __init__(
        self,
        provider: DomainProviderPort,
        checker: DomainCheckerPort,
        repository: ResultRepositoryPort,
        writer: ResultWriter,
    ) -> None:
        """
        Initialize use case.

        Args:
            provider: LLM provider port
            checker: Domain checker port
            repository: Result repository port (cache)
            writer: Result writer for persistence
        """
        self.provider = provider
        self.checker = checker
        self.repository = repository
        self.writer = writer
        self.generator_service = DomainGeneratorService(provider)
        self.check_service = DomainCheckService(checker, repository)

    def execute(self, request: DomainSearchRequest) -> DomainSearchResult:
        """
        Execute domain search use case.

        Args:
            request: Domain search request parameters

        Returns:
            Domain search result with statistics and available domains
        """
        # Clear cache if requested
        if request.clear_cache and isinstance(self.repository, CacheManager):
            self.repository.clear()

        # Global containers
        all_suggested: List[str] = []
        all_available: List[str] = []

        # Create search params
        search_params = DomainSearchParams(
            topic=request.topic,
            tlds=[t.lstrip(".").lower() for t in request.tlds],
            count=request.per_request,
            language=request.language,
            min_len=request.min_len,
            max_len=request.max_len,
        )

        # Pipeline: generate next batch while checking current batch
        # Use ThreadPoolExecutor to overlap generation and checking
        max_pool_workers = max(2, request.llm_workers + 1)  # At least 2: one for gen, one for check

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_pool_workers) as pipeline_pool:
            # Start first generation ahead of time
            gen_future: Optional[concurrent.futures.Future] = None

            for iteration in range(1, request.iterations + 1):
                # Wait for current generation to complete (if any)
                if gen_future is not None:
                    try:
                        candidates = gen_future.result()
                    except ProviderError:
                        # Skip iteration on provider error
                        if iteration < request.iterations:
                            # Start next generation anyway
                            gen_future = pipeline_pool.submit(
                                self._generate_domains_parallel,
                                search_params,
                                request.llm_workers,
                            )
                        time.sleep(request.cooldown)
                        continue
                else:
                    # First iteration - generate synchronously
                    try:
                        candidates = self._generate_domains_parallel(
                            search_params,
                            workers=request.llm_workers,
                        )
                    except ProviderError:
                        time.sleep(request.cooldown)
                        continue

                # Filter out already seen domains
                seen = set(all_suggested)
                if isinstance(self.repository, CacheManager):
                    seen.update(self.repository.known().keys())

                new_candidates = [c for c in candidates if c.name not in seen]

                if not new_candidates:
                    # Start next generation if not last iteration
                    if iteration < request.iterations:
                        gen_future = pipeline_pool.submit(
                            self._generate_domains_parallel,
                            search_params,
                            request.llm_workers,
                        )
                    time.sleep(request.cooldown)
                    continue

                # Start next generation IMMEDIATELY (while we check current batch)
                if iteration < request.iterations:
                    gen_future = pipeline_pool.submit(
                        self._generate_domains_parallel,
                        search_params,
                        request.llm_workers,
                    )

                # Check availability or skip
                if request.skip_check:
                    # Just save without checking
                    for candidate in new_candidates:
                        self.writer.append_available([(candidate.name, "skipped", time.time())])
                    all_available.extend([c.name for c in new_candidates])
                    all_suggested.extend([c.name for c in new_candidates])
                else:
                    # Check domains - this runs in parallel with next generation
                    domain_names = [c.name for c in new_candidates]
                    check_future = pipeline_pool.submit(
                        self.check_service.check_domains_with_cache,
                        domain_names,
                    )

                    # While checking, next generation is already running
                    try:
                        results = check_future.result()
                    except Exception as e:  # noqa: BLE001
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Error checking domains in iteration {iteration}: {e}")
                        results = {}

                    # Save cache
                    if isinstance(self.repository, CacheManager):
                        self.repository.save()

                    # Collect available domains
                    newly_available: List[str] = []
                    to_write = []
                    checked_count = 0
                    available_count = 0
                    
                    # Debug: log what we got
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.debug(
                        f"Iteration {iteration}: checking {len(domain_names)} domains, "
                        f"got {len(results)} results"
                    )
                    
                    for domain, result in results.items():
                        checked_count += 1
                        if result.available:
                            available_count += 1
                            newly_available.append(domain)
                            to_write.append((domain, result.source, result.checked_at))
                        else:
                            logger.debug(
                                f"Domain {domain} is unavailable (source: {result.source})"
                            )

                    # Debug: log statistics for this iteration
                    if checked_count > 0:
                        logger.info(
                            f"Iteration {iteration}: checked {checked_count} domains, "
                            f"found {available_count} available"
                        )
                    elif domain_names:
                        logger.warning(
                            f"Iteration {iteration}: no results returned for {len(domain_names)} domains"
                        )

                    if newly_available:
                        self.writer.append_available(to_write)
                        all_available.extend(newly_available)

                    all_suggested.extend(domain_names)

                time.sleep(request.cooldown)

        # Return result
        return DomainSearchResult(
            total_iterations=request.iterations,
            total_generated=len(set(all_suggested)),
            total_available=len(set(all_available)),
            available_domains=sorted(set(all_available)),
            results_txt=request.results_txt,
            results_csv=request.results_csv,
        )

    def _generate_domains_parallel(
        self,
        params: DomainSearchParams,
        workers: int = 1,
    ) -> List[DomainCandidate]:
        """
        Generate domains with parallel LLM requests.

        Args:
            params: Domain search parameters
            workers: Number of parallel LLM requests

        Returns:
            List of domain candidates
        """
        if workers <= 1:
            return self.generator_service.generate_and_parse(params)

        # Split count across workers
        per_call = max(1, math.ceil(params.count / workers))
        all_candidates: List[DomainCandidate] = []

        # Create modified params for each call
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for _ in range(workers):
                call_params = DomainSearchParams(
                    topic=params.topic,
                    tlds=params.tlds,
                    count=per_call,
                    language=params.language,
                    min_len=params.min_len,
                    max_len=params.max_len,
                )
                futures.append(pool.submit(self.generator_service.generate_and_parse, call_params))

            for future in concurrent.futures.as_completed(futures):
                try:
                    candidates = future.result()
                    all_candidates.extend(candidates)
                except Exception:  # noqa: BLE001
                    # Skip failed requests
                    continue

        # Limit to requested count and remove duplicates
        seen = set()
        unique_candidates = []
        for candidate in all_candidates:
            if candidate.name not in seen and len(unique_candidates) < params.count:
                unique_candidates.append(candidate)
                seen.add(candidate.name)

        return unique_candidates


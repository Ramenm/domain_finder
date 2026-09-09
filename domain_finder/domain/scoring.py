"""Cheap deterministic quality scoring before expensive registry checks."""

from __future__ import annotations

import re

from .models import DomainCandidate


class DomainQualityScorer:
    """Rank structural/name quality without making trademark or language claims."""

    def score(self, candidate: DomainCandidate, topic: str) -> float:
        label = candidate.label.lower()
        length = len(label)
        score = 100.0

        score -= abs(length - 9) * 2.0
        score -= label.count("-") * 10.0
        score -= sum(char.isdigit() for char in label) * 3.0
        if re.search(r"(.)\1\1", label):
            score -= 12.0

        alnum = [char for char in label if char.isalnum()]
        if alnum:
            score += 8.0 * (len(set(alnum)) / len(alnum))

        topic_tokens = {
            token for token in re.findall(r"[a-z0-9]+", topic.lower()) if len(token) >= 4
        }
        if any(token in label for token in topic_tokens):
            score += 8.0

        vowels = sum(char in "aeiouy" for char in label)
        letters = sum(char.isalpha() for char in label)
        if letters and 0.2 <= vowels / letters <= 0.65:
            score += 4.0
        return score

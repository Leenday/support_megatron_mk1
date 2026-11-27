"""A department classifier trained on tickets with a confirmed department (#73).

The model's own confidence does not show its mistakes (an exit token in the prompt changed
almost nothing, #73), so abstaining needs a second, independent opinion. With a labelled
history a trained classifier is that opinion, and a good one: on the EN set it matches the
model with examples (#67), and in the literature it beats prompted LLMs. TF-IDF over
character n-grams with a logistic regression trains in seconds on thousands of tickets,
needs no GPU and gives calibrated probabilities (session 06).
"""

from collections import Counter
from collections.abc import Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline


class DepartmentClassifier:
    """Fitted on (text, department) pairs; predicts a department with its probability."""

    def __init__(self, texts: Sequence[str], departments: Sequence[str]) -> None:
        if len(texts) != len(departments):
            raise ValueError("texts and departments differ in length")
        if len(Counter(departments)) < 2:
            raise ValueError("a classifier needs tickets of at least two departments")
        self.size = len(texts)
        self.pipeline: Pipeline = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2),
            # Balanced: a small department must not lose to a big one only by its size.
            LogisticRegression(max_iter=2000, C=4, class_weight="balanced"),
        )
        self.pipeline.fit(list(texts), list(departments))

    def predict(self, text: str) -> tuple[str, float]:
        """The most probable department and its probability."""
        probabilities = self.pipeline.predict_proba([text])[0]
        best = max(range(len(probabilities)), key=lambda i: probabilities[i])
        return str(self.pipeline.classes_[best]), float(probabilities[best])

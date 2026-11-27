"""Similar solved tickets as examples for the model (#67, step 2).

The model sees only the department descriptions, not how a team actually routes its
requests. For a new request we find the k most similar solved tickets with a confirmed
department and show them before the request. The answer stays an enum of departments, so a
misleading example can only cost a wrong department from the list.

Retrieval is TF-IDF over character n-grams, which needs no model and copes with typos,
inflections and identifiers (session 07: a vector index is a matrix product and a sort).
It is measured on its own (`hit_at_k`) before the answers, since the right department that
is not among the neighbours cannot be learnt from them.
"""

from collections.abc import Sequence

from sklearn.feature_extraction.text import TfidfVectorizer

from megatron.inputs import Request

EXAMPLE_CHARS = 400  # an example is the start of a ticket: enough to see its topic


class ExampleIndex:
    """Solved tickets (`Request` with `expected`) searchable by similarity to a new request.

    `skip_above` leaves out neighbours more similar than that cosine. It is for evaluation on
    data with near-duplicate tickets (the synthetic EN set), where a copy of the test request
    with its label would overstate what examples give; the service keeps it off.
    """

    def __init__(self, solved: Sequence[Request], skip_above: float | None = None) -> None:
        self.solved = [r for r in solved if r.expected]
        if not self.solved:
            raise ValueError("no solved tickets with a department")
        self.skip_above = skip_above
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(r.text for r in self.solved)

    def similar(self, text: str, k: int) -> list[tuple[Request, float]]:
        """The k most similar solved tickets with their cosine, most similar first."""
        scores = (self.matrix @ self.vectorizer.transform([text]).T).toarray().ravel().tolist()
        if self.skip_above is not None:
            scores = [-1.0 if s > self.skip_above else s for s in scores]
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [(self.solved[i], scores[i]) for i in order if scores[i] > 0]


def hit_at_k(index: ExampleIndex, requests: Sequence[Request], k: int) -> float:
    """Share of requests whose expected department is among the k neighbours' departments:
    the ceiling of what the examples can teach (retrieval measured apart from the answer)."""
    labelled = [r for r in requests if r.expected]
    hits = sum(
        any(example.expected == r.expected for example, _ in index.similar(r.text, k))
        for r in labelled
    )
    return hits / len(labelled) if labelled else 0.0


def render_examples(examples: Sequence[tuple[Request, float]]) -> str:
    """The examples as a data block for the user message, one ticket per line."""
    lines = []
    for number, (example, _) in enumerate(examples, 1):
        text = " ".join(example.text.split())
        if len(text) > EXAMPLE_CHARS:
            text = text[:EXAMPLE_CHARS].rsplit(" ", 1)[0] + " …"
        lines.append(f"[{number}] {text} -> {example.expected}")
    return "\n".join(lines)

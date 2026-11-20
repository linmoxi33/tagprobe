"""Candidate revision of the example package."""


def add(a, b):
    return a + b


def scale(x):
    return x * 3


def div(a, b):
    if b == 0:
        raise ValueError("b must be non-zero")
    return a / b


def parse(text):
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"bad number: {text!r}") from None


def tag(name):
    return {"name": name, "kind": "v2"}


def noisy(x):
    return x


def only_b():
    return "added in b"

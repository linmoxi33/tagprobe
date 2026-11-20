"""Baseline revision of the example package."""


def add(a, b):
    return a + b


def scale(x):
    return x * 2


def div(a, b):
    return a / b


def parse(text):
    return int(text)


def tag(name):
    return {"name": name, "kind": "v1"}


def noisy(x):
    print("processing", x)
    return x


def only_a():
    return "removed in b"

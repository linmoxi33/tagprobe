"""tagprobe - run one probe spec against two source trees and diff behaviour."""
from .core import SpecError, compare, load_spec, run, run_tree

__all__ = ["SpecError", "compare", "load_spec", "run", "run_tree"]
__version__ = "0.1.0"

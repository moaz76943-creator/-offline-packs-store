import os
import sys
from collections import defaultdict
import importlib

def test():
    # Dynamic import
    importlib.import_module("os")

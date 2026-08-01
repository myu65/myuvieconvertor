"""Heavy-model entrypoints launched in short-lived subprocesses.

Each stage exits after use so GPU memory is released before the next model loads.
"""

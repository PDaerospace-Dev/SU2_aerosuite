"""Shared pytest configuration."""
import matplotlib

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")

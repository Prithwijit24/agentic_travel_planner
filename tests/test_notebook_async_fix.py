#!/usr/bin/env python
"""Test script to verify the asyncio fix works in a notebook-like environment.

This simulates the Jupyter notebook scenario where asyncio.run() cannot be called
from a running event loop.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentic_tour_planner.cli.plan import _run_async


async def sample_async_function():
    """A simple async function to test the _run_async helper."""
    await asyncio.sleep(0.1)
    return "async_result"


async def test_in_running_loop():
    """Simulate running _run_async from within a running event loop (like Jupyter)."""
    print("Testing _run_async from within a running event loop...")

    # This is what happens in Jupyter - there's already a running loop
    loop = asyncio.get_running_loop()
    print(f"Current running loop: {loop}")

    # Now call _run_async - this should NOT raise RuntimeError
    result = _run_async(sample_async_function())
    print(f"Result: {result}")

    assert result == "async_result", f"Expected 'async_result', got '{result}'"
    print("✓ _run_async works correctly within a running event loop!")
    return True


async def test_outside_running_loop():
    """Test _run_async when there's no running event loop (normal CLI scenario)."""
    print("\nTesting _run_async outside of a running event loop...")

    # Verify no running loop
    try:
        loop = asyncio.get_running_loop()
        print(f"Warning: running loop detected: {loop}")
    except RuntimeError:
        print("No running loop (expected for CLI)")

    # Call _run_async - this should use asyncio.run()
    result = _run_async(sample_async_function())
    print(f"Result: {result}")

    assert result == "async_result", f"Expected 'async_result', got '{result}'"
    print("✓ _run_async works correctly outside a running event loop!")
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing _run_async helper function")
    print("=" * 60)

    # Test 1: Running from within an existing event loop (simulates Jupyter)
    await test_in_running_loop()

    # Test 2: Running from scratch (simulates CLI)
    # We need to exit the current loop context to test this properly
    print("\n" + "=" * 60)
    print("Note: Test 2 runs _run_async in a new thread (simulates CLI)")
    print("=" * 60)

    import concurrent.futures

    def run_test_in_new_thread():
        """Run test outside of any event loop."""
        # Create a fresh event loop
        loop = asyncio.new_event_loop()
        try:
            # Verify no running loop
            try:
                running = asyncio.get_running_loop()
                print(f"Warning: running loop detected in thread: {running}")
            except RuntimeError:
                print("No running loop in thread (expected)")

            # Call _run_async
            result = _run_async(sample_async_function())
            print(f"Result in thread: {result}")
            assert result == "async_result", f"Expected 'async_result', got '{result}'"
            print("✓ _run_async works correctly in a fresh event loop!")
            return True
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_test_in_new_thread)
        success = future.result()

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

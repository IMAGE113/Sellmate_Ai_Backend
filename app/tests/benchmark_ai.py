import asyncio
import time
from app.services.ai_provider import ResilientAIWrapper
from app.services.ai_provider_async import ResilientAIWrapperAsync, OpenAIProviderAsync

async def benchmark_sync():
    # Simulate blocking provider (the old implementation)
    print("Benchmarking Sync (Blocking) Provider...")
    start = time.time()
    # In a real sync scenario, these would block the thread
    # Here we simulate the effect of blocking calls in a worker
    await asyncio.sleep(2.0) 
    end = time.time()
    print(f"Sync Total Time: {end - start:.2f}s")

async def benchmark_async():
    print("Benchmarking Async Provider...")
    provider = OpenAIProviderAsync()
    wrapper = ResilientAIWrapperAsync(provider)
    
    start = time.time()
    # Fire multiple requests concurrently
    tasks = [wrapper.extract("Test prompt", timeout=5.0) for _ in range(5)]
    await asyncio.gather(*tasks)
    end = time.time()
    print(f"Async Total Time (5 concurrent): {end - start:.2f}s")

if __name__ == "__main__":
    asyncio.run(benchmark_async())

import matplotlib.pyplot as plt
import numpy as np

# Performance Metrics for 10 Merchants
merchants = 10
avg_ai_latency = 3.5  # seconds
avg_db_latency = 0.1  # seconds
avg_webhook_latency = 0.05  # seconds
total_latency = avg_ai_latency + avg_db_latency + avg_webhook_latency

# Traffic Projections
msgs_per_merchant_per_hour = 60
total_msgs_per_hour = merchants * msgs_per_merchant_per_hour
msgs_per_second = total_msgs_per_hour / 3600

# Capacity Analysis
worker_concurrency = 1 # current implementation is single loop
processing_capacity_per_sec = worker_concurrency / total_latency
load_percentage = (msgs_per_second / processing_capacity_per_sec) * 100

# Data for Visualization
categories = ['AI Latency', 'DB Latency', 'Webhook Latency']
latencies = [avg_ai_latency, avg_db_latency, avg_webhook_latency]

plt.figure(figsize=(10, 6))
plt.bar(categories, latencies, color=['#3498db', '#e74c3c', '#2ecc71'])
plt.title('Latency Breakdown per Request (Total: ~3.65s)')
plt.ylabel('Time (seconds)')
plt.savefig('/home/ubuntu/latency_breakdown.png')

# Load vs Capacity
labels = ['Current Load (10 Merchants)', 'System Capacity (1 Worker)']
values = [msgs_per_second, processing_capacity_per_sec]

plt.figure(figsize=(10, 6))
plt.bar(labels, values, color=['#f1c40f', '#9b59b6'])
plt.title('Traffic Load vs. Processing Capacity')
plt.ylabel('Requests per Second')
plt.savefig('/home/ubuntu/load_vs_capacity.png')

print(f"Total Latency: {total_latency:.2f}s")
print(f"Messages per Second: {msgs_per_second:.4f}")
print(f"Processing Capacity: {processing_capacity_per_sec:.4f} req/s")
print(f"Estimated Load Percentage: {load_percentage:.2f}%")

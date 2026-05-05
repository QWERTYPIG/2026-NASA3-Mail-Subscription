# test A: Single operation latency baseline
## Operation

- Add then delete a user from aliases

## Data

| Metric | Latency |
|--------|-------|
| min | 7.9 ms |
| p50 | 10.5 ms |
| p95 | 12.9 ms |
| p99 | 13.4 ms |
| max | 13.4 ms |
| mean | 10.4 ms |

# test B: Flush duration vs queue depth
## Operation

Simulates N sequential ldapmodify operations (like a flush with N tasks)

## Data

| N tasks | Total time | ops/sec | vs lock TTL |
|--------:|------------|--------:|------------:|
| 10 | 0.06s | 180.3 | 0.0% |
| 50 | 0.23s | 217.4 | 0.1% |
| 100 | 0.48s | 208.4 | 0.2% |
| 200 | 0.95s | 210.4 | 0.3% |
| 1,000 | 4.41s | 226.8 | 1.5% |
| 5,000 | 22.03s | 227.0 | 7.3% |
| 10,000 | 40.73s | 245.5 | 13.6% |
| 20,000 | 78.34s | 255.3 | 26.1% |
| 50,000 | 208.61s | 239.7 | 69.5% |

# test C: Read latency during writes
## Operation

1. Create two parallel connection
2. One simulate task flushing
3. One simulate ssh login (via ldapsearch)
4. Measure ldapsearch latency

## Data

| Metric | Baseline (no writes) | During flush (sequential writes) |
|--------|---------------------:|---------------------------------:|
| min | 0.5 ms | 0.7 ms |
| p50 | 0.7 ms | 0.8 ms |
| p95 | 1.0 ms | 1.1 ms |
| max | 1.3 ms | 1.7 ms |
| mean | 0.7 ms | 0.9 ms |

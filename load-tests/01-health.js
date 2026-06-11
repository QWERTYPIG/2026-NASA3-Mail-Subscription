/**
 * Scenario 1 — Health check baseline
 *
 * No auth needed. Ramps to 200 VUs to find raw nginx+Django I/O limit.
 * Tracks X-Served-By header to verify round-robin distribution across 3 nodes.
 *
 * Usage:
 *   k6 run load-tests/01-health.js
 *   k6 run --out json=results/health.json load-tests/01-health.js
 */

import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

import { BASE_URL } from './helpers.js';

const nodeHits = {
  mail1: new Counter('node_hits_mail1'),
  mail2: new Counter('node_hits_mail2'),
  mail3: new Counter('node_hits_mail3'),
  unknown: new Counter('node_hits_unknown'),
};

export const options = {
  scenarios: {
    health: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 50 },
        { duration: '1m', target: 200 },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/api/v1/health/`);

  check(res, { 'status 200': (r) => r.status === 200 });

  const node = res.headers['X-Served-By'];
  if (node === 'mail1') nodeHits.mail1.add(1);
  else if (node === 'mail2') nodeHits.mail2.add(1);
  else if (node === 'mail3') nodeHits.mail3.add(1);
  else nodeHits.unknown.add(1);
}
/**
 * Scenario 3 — Authenticated GET subscriptions
 *
 * setup(): batch-login all test users once, collect session tokens.
 * default(): each VU cycles through sessions and hits GET subscriptions.
 * Tests PostgreSQL read + session verification throughput.
 *
 * Usage:
 *   USERS='[{"username":"testuser01","password":"..."},...]' k6 run load-tests/03-read.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';

import { BASE_URL, login, authHeaders, loadUsers } from './helpers.js';

export const options = {
  scenarios: {
    readers: {
      executor: 'ramping-vus',
      startVUs: 10,
      stages: [
        { duration: '1m', target: 100 },
        { duration: '2m', target: 100 },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
  },
};

export function setup() {
  const users = loadUsers();
  const sessions = [];
  for (const u of users) {
    const s = login(u.username, u.password);
    if (s) sessions.push(s);
  }
  if (sessions.length === 0) throw new Error('No sessions established in setup()');
  return { sessions };
}

export default function ({ sessions }) {
  const s = sessions[__VU % sessions.length];
  const res = http.get(`${BASE_URL}/api/v1/user/subscriptions/`, {
    headers: authHeaders(s.sessionid, s.csrftoken),
  });
  check(res, {
    'status 200': (r) => r.status === 200,
    'returns array': (r) => {
      try { return Array.isArray(JSON.parse(r.body)); } catch { return false; }
    },
  });
  sleep(1);
}

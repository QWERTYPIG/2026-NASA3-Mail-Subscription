/**
 * Scenario 4 — PUT subscription rate limiting
 *
 * Each VU uses a distinct user account. Fires 2 PUTs back-to-back.
 * Verifies: 1st → 202 Accepted, 2nd → 429 Too Many Requests.
 * Also confirms Redis TTL keys are per-user (20 users in parallel, no bleed).
 *
 * Usage:
 *   USERS='[{"username":"testuser01","password":"..."},...]' k6 run load-tests/04-rate-limit.js
 *
 * After run, clear rate limit keys:
 *   redis-cli -n 1 KEYS "user_subscription_cooldown:*" | xargs redis-cli -n 1 DEL
 */

import http from 'k6/http';
import { check } from 'k6';

import {
  BASE_URL,
  login,
  getAliasNames,
  authHeaders,
  buildPutBody,
  loadUsers,
} from './helpers.js';

export const options = {
  scenarios: {
    rate_limit_check: {
      executor: 'per-vu-iterations',
      vus: 20,
      iterations: 1,
    },
  },
  thresholds: {
    // All checks must pass — any 429 on first PUT or 202 on second is a bug
    checks: ['rate==1.00'],
  },
};

export function setup() {
  const users = loadUsers();
  const sessions = [];
  for (const u of users) {
    const s = login(u.username, u.password);
    if (s) {
      const aliases = getAliasNames(s.sessionid, s.csrftoken);
      sessions.push({ ...s, aliases });
    }
  }
  if (sessions.length < 20) {
    console.warn(`Only ${sessions.length} sessions; need ≥20 for full coverage`);
  }
  return { sessions };
}

export default function ({ sessions }) {
  const s = sessions[__VU % sessions.length];
  const headers = authHeaders(s.sessionid, s.csrftoken);
  const body = buildPutBody(s.aliases, true);

  const res1 = http.put(`${BASE_URL}/api/v1/user/subscriptions/`, body, { headers });
  check(res1, { 'first PUT accepted (202 or 200)': (r) => r.status === 202 || r.status === 200 });

  const res2 = http.put(`${BASE_URL}/api/v1/user/subscriptions/`, body, { headers });
  check(res2, {
    'second PUT throttled (429)': (r) => r.status === 429,
    'throttle response has wait_seconds': (r) => {
      try {
        return JSON.parse(r.body).details?.wait_seconds > 0;
      } catch { return false; }
    },
  });
}

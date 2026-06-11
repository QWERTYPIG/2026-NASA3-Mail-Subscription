/**
 * Scenario 5 — Mixed realistic load
 *
 * Simulates production traffic distribution:
 *   - 5 VUs  → health check (baseline)
 *   - 10 VUs → login (LDAP auth)
 *   - 70 VUs → GET subscriptions (PostgreSQL reads)
 *   - 15 VUs → PUT subscriptions (write path + queue)
 *
 * Run for 5 minutes. Check node distribution via X-Served-By header.
 *
 * Usage:
 *   USERS='[{"username":"testuser01","password":"..."},...]' \
 *   k6 run --out json=results/mixed.json load-tests/05-mixed.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

import {
  BASE_URL,
  login,
  getAliasNames,
  authHeaders,
  buildPutBody,
  loadUsers,
} from './helpers.js';

const nodeHits = {
  mail1: new Counter('node_hits_mail1'),
  mail2: new Counter('node_hits_mail2'),
  mail3: new Counter('node_hits_mail3'),
  unknown: new Counter('node_hits_unknown'),
};

function trackNode(res) {
  const node = res.headers['X-Served-By'];
  if (node === 'mail1') nodeHits.mail1.add(1);
  else if (node === 'mail2') nodeHits.mail2.add(1);
  else if (node === 'mail3') nodeHits.mail3.add(1);
  else nodeHits.unknown.add(1);
}

export const options = {
  scenarios: {
    health: {
      executor: 'constant-vus',
      vus: 5,
      duration: '5m',
      exec: 'healthCheck',
    },
    login_flow: {
      executor: 'constant-vus',
      vus: 10,
      duration: '5m',
      exec: 'loginFlow',
    },
    readers: {
      executor: 'constant-vus',
      vus: 70,
      duration: '5m',
      exec: 'readSubs',
    },
    writers: {
      executor: 'constant-vus',
      vus: 15,
      duration: '5m',
      exec: 'writeSubs',
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
    if (s) {
      const aliases = getAliasNames(s.sessionid, s.csrftoken);
      sessions.push({ ...s, aliases });
    }
  }
  return { sessions, users };
}

export function healthCheck() {
  const res = http.get(`${BASE_URL}/api/v1/health/`);
  check(res, { 'health 200': (r) => r.status === 200 });
  trackNode(res);
  sleep(0.5);
}

export function loginFlow({ users }) {
  const u = users[__VU % users.length];
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login/`,
    JSON.stringify({ username: u.username, password: u.password }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(res, { 'login 200': (r) => r.status === 200 });
  trackNode(res);
  sleep(3);
}

export function readSubs({ sessions }) {
  const s = sessions[__VU % sessions.length];
  const res = http.get(`${BASE_URL}/api/v1/user/subscriptions/`, {
    headers: authHeaders(s.sessionid, s.csrftoken),
  });
  check(res, { 'read 200': (r) => r.status === 200 });
  trackNode(res);
  sleep(1);
}

export function writeSubs({ sessions }) {
  const s = sessions[__VU % sessions.length];
  const headers = authHeaders(s.sessionid, s.csrftoken);
  const body = buildPutBody(s.aliases, true);
  const res = http.put(`${BASE_URL}/api/v1/user/subscriptions/`, body, { headers });
  check(res, {
    'write accepted or throttled': (r) => r.status === 202 || r.status === 200 || r.status === 429,
  });
  trackNode(res);
  sleep(30); // respect 10-min cooldown per user, but multiple users share VUs
}

/**
 * Scenario 2 — Login stress (LDAP bind bottleneck)
 *
 * Constant-arrival-rate login to find max login QPS before LDAP degrades.
 * Uses round-robin across provided test users so no single account serialises.
 *
 * Usage:
 *   USERS='[{"username":"testuser01","password":"..."},...]' k6 run load-tests/02-login.js
 *
 * After run, clear sessions:
 *   docker exec <db_container> psql -U <user> -d <db> -c "DELETE FROM django_session;"
 */

import http from 'k6/http';
import { check } from 'k6';

import { BASE_URL, loadUsers } from './helpers.js';

const USERS = loadUsers();

export const options = {
  scenarios: {
    login_burst: {
      executor: 'constant-arrival-rate',
      rate: 20,
      timeUnit: '1s',
      duration: '2m',
      preAllocatedVUs: 40,
      maxVUs: 60,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<3000'],
  },
};

export default function () {
  const user = USERS[__VU % USERS.length];
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login/`,
    JSON.stringify({ username: user.username, password: user.password }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(res, {
    'login 200': (r) => r.status === 200,
    'has sessionid cookie': (r) => r.cookies.sessionid !== undefined,
  });
}

import http from "k6/http";
import { check } from "k6";

export const BASE_URL = __ENV.BASE_URL || "https://mailsus.csie.org";
const TEST_USERS = __ENV.USERS ? null : JSON.parse(open("./test-users.json"));

// Returns { sessionid, csrftoken, username } or null on failure
export function login(username, password) {
    const res = http.post(
        `${BASE_URL}/api/v1/auth/login/`,
        JSON.stringify({ username, password }),
        { headers: { "Content-Type": "application/json" }, redirects: 0 },
    );

    if (res.status !== 200) return null;

    const jar = http.cookieJar();
    const cookies = jar.cookiesForURL(`${BASE_URL}/`);
    return {
        username,
        sessionid: cookies.sessionid?.[0]?.value,
        csrftoken: cookies.csrftoken?.[0]?.value,
    };
}

// Returns array of alias_name strings, or [] on failure
export function getAliasNames(sessionid, csrftoken) {
    const res = http.get(`${BASE_URL}/api/v1/user/subscriptions/`, {
        headers: authHeaders(sessionid, csrftoken),
    });
    if (res.status !== 200) return [];
    return JSON.parse(res.body).map((a) => a.alias_name);
}

export function authHeaders(sessionid, csrftoken) {
    return {
        Cookie: `sessionid=${sessionid}; csrftoken=${csrftoken}`,
        "X-CSRFToken": csrftoken,
        "Content-Type": "application/json",
    };
}

// Build a PUT body that toggles nothing (all current state preserved)
// aliases: string[], subscribed: boolean (subscribe all or unsubscribe all)
export function buildPutBody(aliases, subscribed) {
    return JSON.stringify(
        Object.fromEntries(aliases.map((a) => [a, subscribed])),
    );
}

// Parse USERS env var: JSON array of {username, password}
export function loadUsers() {
    if (__ENV.USERS) return JSON.parse(__ENV.USERS);
    return TEST_USERS;
}

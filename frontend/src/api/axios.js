import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1', // ✨ 所有請求都會自動加上這個前綴
  withCredentials: true, // 確保跨域請求也會帶上 Cookie (Session)
  xsrfCookieName: 'csrftoken', 
  xsrfHeaderName: 'X-CSRFToken',
});

export default api;

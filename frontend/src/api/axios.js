import axios from 'axios';

const api = axios.create({
  baseURL: '/api', // ✨ 所有請求都會自動加上這個前綴
  withCredentials: true, // 確保跨域請求也會帶上 Cookie (Session)
});

export default api;

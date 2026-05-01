import React, { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { LogIn, Lock, User, Loader2, Mail } from 'lucide-react';

export default function LoginPage({ currentUser, onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  // 如果已經登入，直接重定向到首頁，防止重複登入
  if (currentUser) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      // 呼叫後端登入 API
      const res = await api.post('/login', { username, password });
      
      if (res.data.user) {
        toast.success(`歡迎回來，${res.data.user.username}！`);
        // 通知 App.jsx 更新全域狀態
        onLoginSuccess(res.data.user);
        navigate('/');
      }
    } catch (err) {
      const errorMsg = err.response?.data?.error || "登入失敗，請檢查帳號密碼";
      toast.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo 區域 */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-600 text-white rounded-2xl shadow-lg mb-4">
            <Mail size={32} />
          </div>
          <h1 className="text-3xl font-bold text-slate-800">Mail Sub</h1>
          <p className="text-slate-500 mt-2">請登入以管理您的郵件訂閱</p>
        </div>

        {/* 登入卡片 */}
        <div className="bg-white p-8 rounded-3xl shadow-xl shadow-slate-200/50 border border-slate-100">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
                <User size={16} className="text-slate-400" /> 帳號名稱
              </label>
              <input
                required
                type="text"
                className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all bg-slate-50 focus:bg-white"
                placeholder="請輸入帳號"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
                <Lock size={16} className="text-slate-400" /> 密碼
              </label>
              <input
                required
                type="password"
                className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all bg-slate-50 focus:bg-white"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 text-white py-3 rounded-xl font-bold hover:bg-indigo-700 active:scale-[0.98] transition-all shadow-lg shadow-indigo-100 flex items-center justify-center gap-2 disabled:opacity-70 disabled:cursor-not-allowed"
            >
              {loading ? (
                <Loader2 className="animate-spin" size={20} />
              ) : (
                <>
                  <LogIn size={20} /> 立即登入
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-slate-100 text-center">
            <p className="text-sm text-slate-400">
              身為管理員？請向系統管理員索取初始帳號。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

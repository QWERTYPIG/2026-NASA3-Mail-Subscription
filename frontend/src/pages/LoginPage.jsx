import React, { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { Mail } from 'lucide-react';
import { Input, Button } from '@csie/ui-library';

export default function LoginPage({ currentUser, onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  if (currentUser) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);

    try {
      const res = await api.post('/auth/login/', { username, password });
      
      if (res.data && res.data.username) {
        toast.success(`歡迎回來，${res.data.username}！`);
        onLoginSuccess({
          username: res.data.username,
          role: res.data.is_staff ? 'admin' : 'user',
          is_admin: res.data.is_staff
        });
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
        
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-600 text-white rounded-2xl shadow-lg mb-4">
            <Mail size={32} />
          </div>
          <h1 className="text-3xl font-bold !text-slate-800">Mail Sub</h1>
          <p className="text-slate-500 mt-2">請登入以管理您的郵件訂閱</p>
        </div>

        <div className="bg-white p-6 sm:p-8 rounded-2xl sm:rounded-3xl shadow-xl shadow-slate-200/50 border border-slate-100 w-full max-w-[90vw] sm:max-w-md">
          <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            
            {/* 修正 onChange，直接接收字串 */}
            <Input 
              label="帳號名稱"
              placeholder="請輸入帳號"
              value={username}
              onChange={(val) => setUsername(val)}
              disabled={loading}
              className="w-full justify-center"
            />

            {/* 修正 onChange，直接接收字串 */}
            <Input 
              label="密碼"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(val) => setPassword(val)}
              disabled={loading}
              className="w-full justify-center"
            />

            <div className="pt-2">
              <Button 
                type="brand" 
                size="lg" 
                leftIcon={loading ? "mdi:loading" : "mdi:login"} 
                onClick={handleSubmit}
                disabled={loading}
                className="w-full justify-center"
              >
                {loading ? "登入中..." : "立即登入"}
              </Button>
            </div>
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

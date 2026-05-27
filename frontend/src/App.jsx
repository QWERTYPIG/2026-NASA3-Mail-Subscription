import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import { LogOut, LogIn, Loader2, User as UserIcon } from 'lucide-react';
import { Toaster } from 'react-hot-toast';

// 引入 Axios 實例
import api from './api/axios';

// 引入自定義組件與頁面
import { ProtectedRoute } from './component';
import { navConfig } from './constants/navConfig';
import {
  HomePage,
  LoginPage,
  AdminAliasPage,
  AliasDetail
} from './pages';

// 建立一個對照表，將路徑對應到實際的組件
const componentMap = {
  '/': HomePage,
  '/manage/aliases': AdminAliasPage
};

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // 1. 檢查登入狀態 (使用 Axios)
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await api.get('/auth/me/');
        // Django returns 200 OK with { username: "...", is_admin: true/false }
        if (res.data && res.data.username) {
          setCurrentUser({
            username: res.data.username,
            is_admin: res.data.is_admin,
            role: res.data.is_admin ? 'admin' : 'user' // Translate boolean to string
          });
        }
      } catch {
        setCurrentUser(null);
      } finally {
        setLoading(false);
      }
    };
    checkAuth();
  }, []);

  // 2. 登出處理
  const handleLogout = async () => {
    try {
      await api.post('/auth/logout/');
      setCurrentUser(null);
      // 直接使用 navigate 或 window.location
      window.location.href = '/login/';
    } catch (err) {
      console.error("登出失敗", err);
    }
  };

  const handleLoginSuccess = (user) => {
    setCurrentUser(user);
  };

  // 載入中畫面
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-blue-600" size={48} />
          <span className="text-gray-600 font-medium tracking-wide">系統載入中...</span>
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Toaster position="top-center" />

      <div className="min-h-screen bg-gray-50 flex flex-col">
        {/* 導覽列 */}
        <nav className="bg-white shadow-sm px-8 py-4 flex justify-between items-center border-b sticky top-0 z-10">
          <div className="flex items-center gap-10">
            <Link to="/" className="font-bold text-2xl text-blue-600 tracking-tighter">Mail</Link>
            
            <div className="flex gap-6">
              {navConfig
                .filter((item) => {
                  // 如果是管理員專屬，檢查角色
                  if (item.adminOnly) {
                    return currentUser?.role === 'admin';
                  }
                  return true;
                })
                .map((item) => (
                  <Link 
                    key={item.path} 
                    to={item.path} 
                    className="flex items-center gap-2 text-gray-600 hover:text-blue-600 font-medium transition-colors"
                  >
                    <item.icon size={18} />
                    <span>{item.label}</span>
                  </Link>
                ))}
            </div>
          </div>

          <div className="flex items-center gap-6">
            {currentUser ? (
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 px-4 py-1.5 bg-blue-50 text-blue-700 rounded-full text-sm font-semibold border border-blue-100">
                  <UserIcon size={14} />
                  <span>{currentUser.username}</span>
                </div>
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 text-red-500 hover:text-red-700 font-medium transition-all"
                >
                  <LogOut size={18} />
                  <span>登出</span>
                </button>
              </div>
            ) : (
              <Link to="/login" className="flex items-center gap-2 text-blue-600 hover:text-blue-800 font-bold">
                <LogIn size={18} />
                <span>登入系統</span>
              </Link>
            )}
          </div>
        </nav>

        {/* 主要內容區 */}
        <main className="flex-grow container mx-auto px-8 py-10">
          <Routes>
            {/* 動態渲染導覽配置中的路由 */}
            {navConfig.map((item) => {
              const Element = componentMap[item.path];
              return (
                <Route 
                  key={item.path} 
                  path={item.path} 
                  element={
                    item.pub ? (
                      <Element currentUser={currentUser} />
                    ) : (
                      <ProtectedRoute user={currentUser}>
                        <Element currentUser={currentUser} />
                      </ProtectedRoute>
                    )
                  } 
                />
              );
            })}

            {/* 登入路由 */}
            <Route 
              path="/login" 
              element={<LoginPage currentUser={currentUser} onLoginSuccess={handleLoginSuccess} />} 
            />

            {/* 管理員專屬：別名細節頁面 */}
            <Route 
              path="/manage/aliases/:id" 
              element={
                <ProtectedRoute user={currentUser} adminOnly={true}>
                  <AliasDetail />
                </ProtectedRoute>
              } 
            />

            {/* 404 重定向 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <footer className="bg-white py-6 text-center text-gray-400 text-sm border-t">
          <p>© 2026 Mail-Subscription Project · Built with React & Django</p>
        </footer>
      </div>
    </BrowserRouter>
  );
}

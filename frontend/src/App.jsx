import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import { LogOut, LogIn, Loader2, User as UserIcon } from 'lucide-react';
import { Toaster } from 'react-hot-toast';

// 1. 引入 UI/UX 團隊的元件
import { Navbar, NavItem, NavDropdown, NavDropdownItem } from '@csie/ui-library';

import api from './api/axios';
import { ProtectedRoute } from './component';
import { navConfig } from './constants/navConfig';
import {
  HomePage,
  LoginPage,
  AdminAliasPage,
  AliasDetail
} from './pages';

const componentMap = {
  '/': HomePage,
  '/manage/aliases': AdminAliasPage
};

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    /*setCurrentUser({
      username: 'layout_tester',
      is_admin: true,
      role: 'admin'
    });
    setLoading(false);*/
    const checkAuth = async () => {
      try {
        const res = await api.get('/auth/me/');
        if (res.data && res.data.username) {
          setCurrentUser({
            username: res.data.username,
            is_admin: res.data.is_admin,
            role: res.data.is_admin ? 'admin' : 'user'
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

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout/');
      setCurrentUser(null);
      window.location.href = '/login/';
    } catch (err) {
      console.error("登出失敗", err);
    }
  };

  const handleLoginSuccess = (user) => {
    setCurrentUser(user);
  };

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

      <div className="min-h-screen bg-gray-100 flex flex-col">
        
        {/* 替換為團隊開發的 Navbar */}
        <Navbar 
          brandText="Mail Sub" 
          defaultActive={window.location.pathname}
        >
          {/* 左側：動態渲染導覽列項目 */}
          {navConfig
            .filter((item) => item.adminOnly ? currentUser?.role === 'admin' : true)
            .map((item) => (
              <NavItem key={item.path} name={item.path} className="relative">
                <Link to={item.path} className="flex items-center gap-2 w-full h-full before:absolute before:inset-0">
                  <item.icon size={18} />
                  <span>{item.label}</span>
                </Link>
              </NavItem>
            ))}

          {/* 右側：使用者狀態與下拉選單 */}
          {currentUser ? (
            <NavDropdown
              alignRight
              trigger={
                <NavItem name="user-profile">
                  <div className="flex items-center gap-2">
                    <UserIcon size={16} />
                    <span>{currentUser.username} {currentUser.role === 'admin' ? '(管理員)' : ''}</span>
                  </div>
                </NavItem>
              }
            >
              <NavDropdownItem name="logout">
                <button 
                  onClick={handleLogout} 
                  className="flex items-center gap-2 text-red-500 hover:text-red-600 w-full text-left"
                >
                  <LogOut size={16} />
                  <span>安全登出</span>
                </button>
              </NavDropdownItem>
            </NavDropdown>
          ) : (
            <NavItem name="login" className="relative">
              <Link to="/login" className="flex items-center gap-2 w-full h-full text-blue-600 font-bold before:absolute before:inset-0">
                <LogIn size={16} />
                <span>登入系統</span>
              </Link>
            </NavItem>
          )}
        </Navbar>

        {/* 主要內容區 */}
        <main className="flex-grow container mx-auto px-4 md:px-8 py-6 md:py-10 w-full overflow-x-hidden">
          <Routes>
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

            <Route 
              path="/login" 
              element={<LoginPage currentUser={currentUser} onLoginSuccess={handleLoginSuccess} />} 
            />

            <Route 
              path="/manage/aliases/:id" 
              element={
                <ProtectedRoute user={currentUser} adminOnly={true}>
                  <AliasDetail />
                </ProtectedRoute>
              } 
            />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <footer className="bg-white py-6 text-center text-gray-400 text-sm border-t mt-auto">
          <p>© 2026 Mail-Subscription Project · Built with React & Django</p>
        </footer>
      </div>
    </BrowserRouter>
  );
}

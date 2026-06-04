import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

export default function ProtectedRoute({ user, adminOnly = false, children }) {
  const location = useLocation();

  // 1. 如果沒有登入，強制導向登入頁，並記住原本想去的地方
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 2. 如果這頁需要管理員權限，但使用者不是管理員，踢回首頁
  if (adminOnly && user.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  // 3. 通過檢查，渲染原件
  return children;
}

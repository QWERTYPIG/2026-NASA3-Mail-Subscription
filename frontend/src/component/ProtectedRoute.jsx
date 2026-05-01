import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

/**
 * @param {Object} user - 從 App.jsx 傳入的 currentUser 物件
 * @param {boolean} adminOnly - 是否限制只有管理員可進入
 * @param {React.ReactNode} children - 要保護的頁面內容
 */
const ProtectedRoute = ({ user, adminOnly = false, children }) => {
  const location = useLocation();

  // 1. 檢查是否登入
  if (!user) {
    // 將使用者原本想去的路徑存起來 (state)，登入成功後可以跳轉回來
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 2. 如果頁面要求管理員權限，但使用者不是 admin
  if (adminOnly && user.role !== 'admin') {
    // 權限不足，退回首頁
    return <Navigate to="/" replace />;
  }

  // 3. 驗證通過，渲染子組件
  return children;
};

export default ProtectedRoute;

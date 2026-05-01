import React, { useState, useEffect } from 'react';
import api from '../api/axios'; // 確保你使用了帶有 withCredentials 的 axios 實體
import { toast } from 'react-hot-toast';
import { Mail, CheckCircle2, Circle, Loader2, Info } from 'lucide-react';

export default function AliasPage() {
  const [aliases, setAliases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState(null); // 用於顯示特定按鈕的載入狀態

  // 1. 取得別名清單與訂閱狀態
  const fetchAliases = async () => {
    try {
      const res = await api.get('/aliases');
      setAliases(res.data);
    } catch {
      toast.error("無法載入訂閱清單");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAliases();
  }, []);

  // 2. 處理訂閱切換 (Toggle)
  const handleToggle = async (aliasId, currentStatus) => {
    setProcessingId(aliasId);
    const action = currentStatus ? 'unsub' : 'sub';
    
    try {
      await api.post('/subscribe', { alias_id: aliasId, action });
      
      // 樂觀更新 (Optimistic UI Update) 或直接重新抓取
      setAliases(prev => prev.map(a => 
        a.id === aliasId ? { ...a, is_subscribed: !currentStatus } : a
      ));
      
      toast.success(currentStatus ? "已取消訂閱" : "訂閱成功！");
    } catch {
      toast.error("操作失敗，請稍後再試");
    } finally {
      setProcessingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64">
        <Loader2 className="animate-spin text-indigo-500 mb-2" size={32} />
        <p className="text-slate-500">正在準備您的郵件清單...</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
          <Mail className="text-indigo-600" /> 郵件別名訂閱管理
        </h1>
        <p className="text-slate-500 mt-1">
          在此管理您感興趣的郵件群組，訂閱後您將會收到發往該別名的郵件。
        </p>
      </header>

      {aliases.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-slate-200 rounded-xl p-12 text-center">
          <p className="text-slate-400">目前沒有可用的郵件別名</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {aliases.map((alias) => (
            <div 
              key={alias.id} 
              className={`group bg-white p-5 rounded-xl border transition-all duration-200 flex items-center justify-between ${
                alias.is_subscribed 
                ? 'border-indigo-100 shadow-sm ring-1 ring-indigo-50' 
                : 'border-slate-200 hover:border-slate-300 shadow-none'
              }`}
            >
              <div className="flex items-start gap-4">
                <div className={`mt-1 p-2 rounded-lg ${alias.is_subscribed ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-50 text-slate-400'}`}>
                  {alias.is_subscribed ? <CheckCircle2 size={20} /> : <Circle size={20} />}
                </div>
                <div>
                  <h3 className="font-bold text-slate-800 text-lg uppercase tracking-tight">
                    {alias.name}
                  </h3>
                  <p className="text-slate-500 text-sm mt-0.5 leading-relaxed">
                    {alias.description || "尚無描述"}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-4">
                {/* 使用者看到的 Toggle 按鈕 */}
                <button
                  onClick={() => handleToggle(alias.id, alias.is_subscribed)}
                  disabled={processingId === alias.id}
                  className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                    alias.is_subscribed ? 'bg-indigo-600' : 'bg-slate-200'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform duration-200 ease-in-out ${
                      alias.is_subscribed ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                  {processingId === alias.id && (
                    <div className="absolute inset-0 flex items-center justify-center bg-white/20 rounded-full">
                      <Loader2 className="animate-spin text-white" size={14} />
                    </div>
                  )}
                </button>

                <span className={`text-sm font-semibold w-16 text-right ${
                  alias.is_subscribed ? 'text-indigo-600' : 'text-slate-400'
                }`}>
                  {alias.is_subscribed ? '已訂閱' : '未訂閱'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      <footer className="mt-10 bg-slate-100 p-4 rounded-lg flex items-start gap-3 border border-slate-200">
        <Info className="text-slate-400 shrink-0 mt-0.5" size={18} />
        <p className="text-xs text-slate-600">
          <b>提示：</b> 訂閱變更可能需要幾分鐘的時間才會生效。如果您停止接收某個別名的郵件，請確認您在此處已取消勾選。
        </p>
      </footer>
    </div>
  );
}

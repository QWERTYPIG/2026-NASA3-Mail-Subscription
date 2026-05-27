import React, { useState, useEffect } from 'react';
import api from '../api/axios'; 
import { toast } from 'react-hot-toast';
import { Mail, CheckCircle2, Circle, Loader2, Info, Save } from 'lucide-react';

// 1. 接收 currentUser prop
export default function AliasPage({ currentUser }) {
  const [aliases, setAliases] = useState([]);
  const [originalAliases, setOriginalAliases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false); 
  const [hasChanges, setHasChanges] = useState(false);

  // 判斷是否為一般使用者 (只有一般使用者可以訂閱)
  const isNormalUser = !currentUser?.is_admin;

  const fetchAliases = async () => {
    try {
      // 如果是 Admin，可能需要呼叫 admin endpoints，但為了顯示列表，我們先保留原本的 API，或者依賴後端的權限設計
      const endpoint = isNormalUser ? '/user/subscriptions/' : '/manage/aliases/';
      const res = await api.get(endpoint);
      setAliases(res.data);
      //save original aliases state
      if (isNormalUser) {
        setOriginalAliases(JSON.parse(JSON.stringify(res.data)));
        setHasChanges(false);
      }
    } catch {
      toast.error("無法載入訂閱清單");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAliases();
  }, [isNormalUser]); // 加入 dependency

  const handleToggle = (aliasName) => {
    if (!isNormalUser) return;
    
    setAliases(prev => {
      const newAliases = prev.map(a => 
        a.alias_name === aliasName ? { ...a, is_subscribed: !a.is_subscribed } : a
      );
      
      // check if aliases are changed
      const isDifferent = JSON.stringify(newAliases) !== JSON.stringify(originalAliases);
      setHasChanges(isDifferent);
      
      return newAliases;
    });
  };

  const handleSave = async () => {
    if (!isNormalUser || !hasChanges) return;
    setIsSaving(true);

    const payload = {};
    aliases.forEach(a => {
      payload[a.alias_name] = a.is_subscribed;
    });
    
    try {
      await api.put('/user/subscriptions/', payload);
      toast.success("已收到訂閱狀態更新請求，將於 10 分鐘內生效");
      setOriginalAliases(JSON.parse(JSON.stringify(aliases)));
      setHasChanges(false);
    } catch (err) {
      if (err.response?.status === 429) {
        toast.error(err.response.data.detail || "操作過於頻繁，請稍後再試");
      } else {
        toast.error("操作失敗，請稍後再試");
      }
    } finally {
      setIsSaving(false);
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
        <h1 className="text-2xl font-bold !text-slate-800 flex items-center gap-2">
          <Mail className="text-indigo-600" /> {isNormalUser ? "郵件別名訂閱管理" : "郵件別名總覽"}
        </h1>
        <p className="text-slate-500 mt-1">
          {isNormalUser 
            ? "在此管理您感興趣的郵件群組，訂閱後您將會收到發往該別名的郵件。"
            : "身為管理員，您可以在此查看系統中所有的郵件別名。請至「別名系統管理」進行修改。"}
        </p>
      </header>

      {aliases.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-slate-200 rounded-xl p-12 text-center">
          <p className="text-slate-400">目前沒有可用的郵件別名</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {aliases.map((alias) => {
            // check if aliases were changed
            const originalAlias = originalAliases.find(a => a.alias_name === alias.alias_name);
            const isModified = originalAlias && originalAlias.is_subscribed !== alias.is_subscribed;

            return (
              <div 
                key={alias.alias_name} 
                className={`group bg-white p-5 rounded-xl border transition-all duration-200 flex items-center justify-between ${
                  isModified ? 'border-amber-300 bg-amber-50/30' // hint that the alias was modified but not saved
                  : ((isNormalUser && alias.is_subscribed) 
                    ? 'border-indigo-100 shadow-sm ring-1 ring-indigo-50' 
                    : 'border-slate-200 hover:border-slate-300 shadow-none')
                }`}
              >
                <div className="flex items-start gap-4">
                  <div className={`mt-1 p-2 rounded-lg ${
                    (isNormalUser && alias.is_subscribed) ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-50 text-slate-400'
                  }`}>
                    {!isNormalUser ? <Mail size={20} /> : (alias.is_subscribed ? <CheckCircle2 size={20} /> : <Circle size={20} />)}
                  </div>
                  <div>
                    <h3 className="font-bold text-slate-800 text-lg uppercase tracking-tight flex items-center gap-2">
                      {alias.display_name || alias.alias_name}
                      {isModified && <span className="text-[10px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-bold">未儲存</span>}
                    </h3>
                    <p className="text-slate-500 text-sm mt-0.5 leading-relaxed">
                      {alias.description || "尚無描述"}
                    </p>
                  </div>
                </div>

                {isNormalUser && (
                  <div className="flex items-center gap-4">
                    <button
                      onClick={() => handleToggle(alias.alias_name)}
                      className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                        alias.is_subscribed ? 'bg-indigo-600' : 'bg-slate-200'
                      }`}
                    >
                      <span
                        className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform duration-200 ease-in-out ${
                          alias.is_subscribed ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>

                    <span className={`text-sm font-semibold w-16 text-right ${
                      alias.is_subscribed ? 'text-indigo-600' : 'text-slate-400'
                    }`}>
                      {alias.is_subscribed ? '已訂閱' : '未訂閱'}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {isNormalUser && (
        <>
          {/* 儲存按鈕區塊 */}
          <div className="mt-8 flex justify-end border-t border-slate-200 pt-6">
            <button
              onClick={handleSave}
              disabled={!hasChanges || isSaving}
              className={`flex items-center gap-2 px-8 py-3 rounded-xl font-bold text-lg transition-all ${
                hasChanges 
                  ? 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-lg shadow-indigo-200 active:scale-[0.98]' 
                  : 'bg-slate-100 text-slate-400 cursor-not-allowed'
              }`}
            >
              {isSaving ? <Loader2 className="animate-spin" size={20} /> : <Save size={20} />}
              儲存變更
            </button>
          </div>

          {/* 提示區塊 */}
          <footer className="mt-6 bg-slate-50 p-4 rounded-lg flex items-start gap-3 border border-slate-200">
            <Info className="text-slate-400 shrink-0 mt-0.5" size={18} />
            <p className="text-xs text-slate-600">
              <b>提示：</b> 變更送出後將進入 10 分鐘冷卻期，請確認勾選無誤後再行儲存。如果停止接收某個別名的郵件，請確認您在此處已取消勾選。
            </p>
          </footer>
        </>
      )}
    </div>
  );
}

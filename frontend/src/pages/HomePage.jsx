import React, { useState, useEffect } from 'react';
import api from '../api/axios'; 
import { toast } from 'react-hot-toast';
import { Loader2 } from 'lucide-react';

// 1. 引入 UI/UX 團隊的元件
import { 
  PageHeader, 
  Button, 
  RecordCard, 
  Badge, 
  Toggle, 
  HelpText, 
  SuccessIcon, 
  InfoIcon 
} from '@csie/ui-library';

export default function HomePage({ currentUser }) {
  const [aliases, setAliases] = useState([]);
  const [originalAliases, setOriginalAliases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false); 
  const [hasChanges, setHasChanges] = useState(false);

  const isNormalUser = !currentUser?.is_admin;

  const fetchAliases = async () => {
    try {
      const endpoint = isNormalUser ? '/user/subscriptions/' : '/manage/aliases/';
      const res = await api.get(endpoint);
      setAliases(res.data);
      
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
  }, [isNormalUser]);

  const handleToggle = (aliasName) => {
    if (!isNormalUser) return;
    
    setAliases(prev => {
      const newAliases = prev.map(a => 
        a.alias_name === aliasName ? { ...a, is_subscribed: !a.is_subscribed } : a
      );
      
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
      toast.success("已收到訂閱狀態更新請求，將於 30 分鐘內生效");
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
    // 1. The full-screen canvas. flex-col is CRITICAL here so items stack top-to-bottom!
    <div className="w-full min-h-screen flex flex-col items-center bg-gray-100 py-8 px-4 gap-6">

    {/* 2. HEADER TIER: Wider (max-w-5xl) to give the button room */}
      {/* We use a custom flex row here to forcefully align the Title and Button */}
      <div className="w-full max-w-5xl flex flex-row items-center justify-between bg-white p-6 rounded-2xl shadow-sm">
        
        {/* Left Side: Just the TitleArea */}
        <div className="flex-1 [&>*]:!border-none [&_*]:!shadow-none [&_hr]:hidden">
          {/* We strip out the internal ActionArea and TopRight since we are handling layout ourselves */}
          <PageHeader>
            <PageHeader.TitleArea
              title={
                // Wrap the title in a span to force it to be larger (text-3xl or text-4xl)
                <span className="text-3xl sm:text-4xl font-extrabold tracking-tight">
                  {isNormalUser ? "郵件別名訂閱管理" : "郵件別名總覽"}
                </span>
              } 
              breadcrumb={
                // Wrap the breadcrumb to increase its size slightly and add spacing
                <span className="text-base sm:text-lg text-slate-500 mt-2 inline-block">
                  首頁 / 郵件別名
                </span>
              }
            />
          </PageHeader>
        </div>

        {/* Right Side: The Button (extracted out of the UI library's constraints) */}
        <div className="flex-shrink-0 ml-4">
          {isNormalUser && (
            <Button 
              type="brand" 
              size="lg" 
              leftIcon={isSaving ? "mdi:loading" : "mdi:content-save"} 
              onClick={handleSave}
              disabled={!hasChanges || isSaving}
            >
              {isSaving ? '儲存中...' : '儲存變更'}
            </Button>
          )}
        </div>
      </div>
      {/* 3. CONTENT TIER: Narrower (max-w-4xl) to create visual hierarchy */}
      <div className="w-full max-w-4xl flex flex-col gap-6 p-6 sm:p-8 bg-gray-50 rounded-2xl shadow-sm">
        
        {isNormalUser && (
          <HelpText size="L" status="info">
            提示：變更送出後將進入 10 分鐘冷卻期。如果停止接收某個別名的郵件，請確認您在此處已取消勾選。
          </HelpText>
        )}

        {aliases.length === 0 ? (
          <HelpText size="L" status="warning">目前沒有可用的郵件別名</HelpText>
        ) : (
          <div className="w-full flex flex-col gap-4 items-stretch [&>*]:w-full [&>*]:!max-w-none">
            {aliases.map((alias) => {
              const originalAlias = originalAliases.find(a => a.alias_name === alias.alias_name);
              const isModified = originalAlias && originalAlias.is_subscribed !== alias.is_subscribed;

              return (
                <RecordCard
                  key={alias.alias_name}
                  header={
                    <div className="flex items-center gap-3">
                      {!isNormalUser ? <InfoIcon size={24} /> : (alias.is_subscribed ? <SuccessIcon size={24} /> : <InfoIcon size={24} />)}
                      <h3 className="m-0 text-[20px] font-semibold text-black">
                        <span className="whitespace-normal break-all max-w-full inline-block text-left">
                            {alias.display_name || alias.alias_name}
                        </span>
                      </h3>
                    </div>
                  }
                  actions={
                    isNormalUser && (
                      <div className="flex items-center gap-4">
                        <span className={`text-sm font-bold ${alias.is_subscribed ? 'text-indigo-600' : 'text-slate-400'}`}>
                          {alias.is_subscribed ? '已訂閱' : '未訂閱'}
                        </span>
                        <div onClick={() => handleToggle(alias.alias_name)}>
                          <Toggle checked={alias.is_subscribed} />
                        </div>
                      </div>
                    )
                  }
                >
                  <div className="flex flex-wrap items-center gap-3 mt-1">
                    <Badge type="info" text={
                    <span className="whitespace-normal break-all max-w-full inline-block text-left">
                      {alias.description || "暫無描述"}
                    </span>}/>
                    {isModified && <Badge type="state" variant="neutral" text="未儲存" />}
                  </div>
                </RecordCard>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

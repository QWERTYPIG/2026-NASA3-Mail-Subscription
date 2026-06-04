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
    // 1. The outer flex container centers everything
    <div className="w-full flex justify-center pb-12">
      
      {/* 2. Increased to max-w-5xl so the PageHeader doesn't overflow */}
      <div className="w-full max-w-5xl flex flex-col gap-6">
        
        {/* PageHeader is now strictly bound by the 5xl container */}
        <PageHeader>
          <PageHeader.TitleArea 
            title={isNormalUser ? "郵件別名訂閱管理" : "郵件別名總覽"} 
            breadcrumb="首頁 / 郵件別名" 
          />
          <PageHeader.TopRight />
          <PageHeader.ActionArea>
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
          </PageHeader.ActionArea>
        </PageHeader>

        {isNormalUser && (
          <HelpText size="L" status="info">
            提示：變更送出後將進入 10 分鐘冷卻期。如果停止接收某個別名的郵件，請確認您在此處已取消勾選。
          </HelpText>
        )}

        {aliases.length === 0 ? (
          <HelpText size="L" status="warning">目前沒有可用的郵件別名</HelpText>
        ) : (
          <div className="flex flex-col gap-4 w-full">
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
                        {alias.display_name || alias.alias_name}
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
                    <Badge type="info" text={alias.description || "尚無描述"} />
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

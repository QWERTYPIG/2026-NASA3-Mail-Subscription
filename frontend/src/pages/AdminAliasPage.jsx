import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { Loader2, Mail } from 'lucide-react';
import { 
  PageHeader, 
  Button, 
  RecordCard, 
  Badge, 
  Input
} from '@csie/ui-library';

const AdminAliasPage = () => {
  const navigate = useNavigate();
  const [aliases, setAliases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [newAlias, setNewAlias] = useState({ name: '', description: '' });

  const fetchAliases = async () => {
    try {
      const res = await api.get('/manage/aliases/');
      setAliases(res.data);
    } catch {
      toast.error("無法取得別名清單");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAliases(); }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await api.post('/manage/aliases/', {
        alias_name: newAlias.name,       
        display_name: newAlias.name,     
        description: newAlias.description          
      });
      toast.success("別名建立成功");
      setShowModal(false);
      setNewAlias({ name: '', description: '' });
      fetchAliases();
    } catch {
      toast.error("建立失敗，名稱可能已存在");
    }
  };

  const handleDelete = async (aliasName, displayName) => {
    if (!window.confirm(`確定要刪除群組「${displayName}」嗎？此動作不可逆。`)) return;
    try {
      await api.delete(`/manage/aliases/${aliasName}/`);
      toast.success("已成功刪除別名");
      fetchAliases(); 
    } catch {
      toast.error("刪除失敗");
    }
  };

  if (loading) return <div className="flex justify-center p-20"><Loader2 className="animate-spin text-indigo-600" size={40} /></div>;
  return (
    // 1. The full-screen canvas. flex-col keeps items stacked top-to-bottom and centered!
    <div className="w-full min-h-screen flex flex-col items-center bg-gray-100 py-8 px-4 gap-6">

      {/* 2. HEADER TIER: Unified White Card Container (max-w-5xl) */}
      <div className="w-full max-w-5xl flex flex-row items-center justify-between bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
        
        {/* Left Side: The TitleArea with enlarged text */}
        <div className="flex-1 [&>*]:!border-none [&_*]:!shadow-none [&_hr]:hidden">
          <PageHeader>
            <PageHeader.TitleArea 
              title={
                <span className="text-3xl sm:text-4xl font-extrabold tracking-tight">
                  別名系統管理
                </span>
              } 
              breadcrumb={
                <span className="text-base sm:text-lg text-slate-500 mt-2 inline-block">
                  首頁 / 別名管理
                </span>
              } 
            />
          </PageHeader>
        </div>

        {/* Right Side: The Button (extracted to sit perfectly on the same line) */}
        <div className="flex-shrink-0 ml-4">
          <Button type="brand" size="lg" leftIcon="mdi:plus" onClick={() => setShowModal(true)}>
            新增別名
          </Button>
        </div>
      </div>

      {/* 3. CONTENT TIER: Narrower (max-w-4xl) to create visual hierarchy */}
      <div className="w-full max-w-4xl flex flex-col gap-6 p-6 sm:p-8 bg-gray-50 rounded-2xl shadow-sm">
        
        <div className="w-full flex flex-col gap-4 items-stretch [&>*]:w-full [&>*]:!max-w-none">
          {aliases.map(alias => (
            <RecordCard
              key={alias.alias_name}
              header={
                <div className="flex items-center gap-4">
                  <div className="bg-slate-300 p-2.5 rounded-full text-indigo-600">
                    <Mail size={22} />
                  </div>
                  <h3 className="m-0 text-[20px] font-semibold text-black">
                    {alias.display_name || alias.alias_name}
                  </h3>
                </div>
              }
              actions={
                <div className="flex items-center gap-2">
                  <Button type="brand" size="sm" leftIcon="mdi:cog" onClick={() => navigate(`/manage/aliases/${alias.alias_name}`)}>
                    管理設定
                  </Button>
                  <Button type="danger" size="sm" leftIcon="mdi:trash-can-outline" onClick={() => handleDelete(alias.alias_name, alias.display_name || alias.alias_name)}>
                    刪除
                  </Button>
                </div>
              }
            >
              <div className="mt-2 [&_*]:!whitespace-normal [&_*]:break-words [&_*]:text-left w-full">
                <Badge type="info" text={alias.description || "暫無描述"}/>
              </div>
            </RecordCard>
          ))}
        </div>
      </div>

      {/* 4. MODAL: Stays safely outside the layout boxes */}
      {showModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-[100]">
           <form onSubmit={handleCreate} className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 sm:p-8 m-4 space-y-6 animate-in zoom-in-95 duration-200">
            <h2 className="text-xl font-bold text-slate-800">建立新郵件別名</h2>
            <div className="space-y-4">
              <Input 
                label="別名名稱 (例如: security-alerts)"
                placeholder="輸入別名..."
                value={newAlias.name}
                onChange={(val) => setNewAlias({...newAlias, name: val})}
              />
              <Input 
                label="描述說明"
                placeholder="簡單描述此群組用途..."
                value={newAlias.description}
                onChange={(val) => setNewAlias({...newAlias, description: val})}
              />
            </div>
            <div className="flex gap-3 pt-4">
              <div className="flex-1" onClick={() => setShowModal(false)}>
                <Button type="default" className="w-full justify-center">取消</Button>
              </div>
              <div className="flex-1" onClick={handleCreate}>
                <Button type="brand" className="w-full justify-center">確認建立</Button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

export default AdminAliasPage;

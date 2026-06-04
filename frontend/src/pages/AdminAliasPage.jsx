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
    <div className="w-full flex justify-center pb-12">
      
      {/* Both Header and Cards share this exact max-w-5xl box */}
      <div className="w-full max-w-5xl flex flex-col gap-6">
        
        <PageHeader>
          <PageHeader.TitleArea title="別名系統管理" breadcrumb="首頁 / 別名管理" />
          <PageHeader.TopRight />
          <PageHeader.ActionArea>
            <Button type="brand" size="lg" leftIcon="mdi:plus" onClick={() => setShowModal(true)}>
              新增別名
            </Button>
          </PageHeader.ActionArea>
        </PageHeader>

        <div className="flex flex-col gap-4 w-full">
          {aliases.map(alias => (
            <RecordCard
              key={alias.alias_name}
              header={
                <div className="flex items-center gap-4">
                  <div className="bg-indigo-50 p-2.5 rounded-full text-indigo-600">
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
              <div className="mt-2">
                <Badge type="info" text={alias.description || "暫無描述"} />
              </div>
            </RecordCard>
          ))}
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-[100]">
           {/* ... Modal form code remains exactly the same ... */}
        </div>
      )}
    </div>
  );
}

export default AdminAliasPage;

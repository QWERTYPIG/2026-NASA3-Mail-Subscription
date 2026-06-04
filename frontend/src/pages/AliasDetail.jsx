import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { Loader2 } from 'lucide-react';
import { Input, Button, TableList, HelpText, PageHeader } from '@csie/ui-library';

const AliasDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const [alias, setAlias] = useState({ display_name: '', description: '' });
  const [allMembers, setAllMembers] = useState([]); 
  const [newUid, setNewUid] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => { 
    const fetchData = async () => {
      try {
        const aliasRes = await api.get('/manage/aliases/');
        const currentAlias = aliasRes.data.find(a => a.alias_name === id);
        
        if (!currentAlias) throw new Error("Alias not found");
        setAlias(currentAlias);

        const membersRes = await api.get(`/manage/aliases/${id}/users/`);
        const formattedMembers = membersRes.data.map(uid => ({ id: uid, uid }));
        setAllMembers(formattedMembers);
      } catch {
        toast.error("無法載入資料");
        navigate('/manage/aliases/'); 
      } finally {
        setLoading(false);
      }
    };
    fetchData(); 
  }, [id, navigate]);

  const handleUpdateAlias = async (e) => {
    if (e) e.preventDefault();
    setSaving(true);
    try {
      await api.patch(`/manage/aliases/${id}/`, {
        display_name: alias.display_name,
        description: alias.description
      });
      toast.success("設定更新成功");
    } catch {
      toast.error("更新失敗，請檢查輸入內容");
    } finally {
      setSaving(false);
    }
  };

  const handleAddMember = async (e) => {
    if (e) e.preventDefault();
    if (!newUid.trim()) return;
    
    try {
      await api.post(`/manage/aliases/${id}/users/`, { uid: newUid.trim() });
      toast.success(`已將 ${newUid} 加入群組`);
      setAllMembers(prev => [...prev, { id: newUid.trim(), uid: newUid.trim() }]);
      setNewUid('');
    } catch (err) {
      toast.error(err.response?.data?.error || "加入失敗，請確認 UID 正確");
    }
  };

  const handleRemoveMember = async (uidToRemove) => {
    if (!window.confirm(`確定要將 ${uidToRemove} 從此群組移除嗎？`)) return;
    
    try {
      await api.delete(`/manage/aliases/${id}/users/${uidToRemove}/`);
      toast.success(`已移除 ${uidToRemove}`);
      setAllMembers(prev => prev.filter(m => m.uid !== uidToRemove));
    } catch {
      toast.error("移除失敗");
    }
  };

  if (loading) return <div className="flex justify-center p-20"><Loader2 className="animate-spin text-indigo-600" size={40} /></div>;

  return (
    <div className="w-full bg-[#F8F9FA] min-h-screen">
      <PageHeader>
        <PageHeader.TitleArea title={`別名設定 (${id})`} breadcrumb="首頁 / 別名管理 / 設定" />
        <PageHeader.TopRight />
        <PageHeader.ActionArea>
          <Button type="default" size="lg" leftIcon="mdi:arrow-left" onClick={() => navigate('/manage/aliases')}>
            返回清單
          </Button>
        </PageHeader.ActionArea>
      </PageHeader>
        
      <div className="p-4 md:p-8 w-full max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8">
        <div className="md:col-span-1">
          <section className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm sticky top-24 space-y-6">
            <h2 className="text-lg font-bold text-slate-800">基本資訊</h2>
            <form onSubmit={handleUpdateAlias} className="space-y-6">
              {/* 修正 onChange */}
              <Input 
                label="顯示名稱"
                value={alias.display_name || ''}
                onChange={(val) => setAlias({...alias, display_name: val})}
              />
              {/* 修正 onChange */}
              <Input 
                label="描述說明"
                value={alias.description || ''}
                onChange={(val) => setAlias({...alias, description: val})}
              />
              <Button type="brand" className="w-full justify-center" disabled={saving} leftIcon={saving ? "mdi:loading" : "mdi:content-save"} onClick={handleUpdateAlias}>
                {saving ? "儲存中" : "儲存變更"}
              </Button>
            </form>
          </section>
        </div>

        <div className="md:col-span-2 space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="p-6 bg-slate-50 border-b border-slate-200">
              <h2 className="text-lg font-bold text-slate-800 mb-4">成員管理</h2>
              <form onSubmit={handleAddMember} className="flex flex-col sm:flex-row gap-4 sm:items-end">
                <div className="flex-1">
                  {/* 修正 onChange */}
                  <Input 
                    label="新增成員"
                    placeholder="輸入學生/員工 UID (例如: b13902001)"
                    value={newUid}
                    onChange={(val) => setNewUid(val)}
                  />
                </div>
                <Button type="brand" leftIcon="mdi:account-plus" onClick={handleAddMember}>加入</Button>
              </form>
            </div>

            <div className="p-4">
              {allMembers.length === 0 ? (
                <div className="p-8 text-center">
                  <HelpText size="L" status="default">目前無訂閱成員</HelpText>
                </div>
              ) : (
                <TableList
                  data={allMembers}
                  columns={[
                    {
                      header: '成員 UID',
                      accessor: (d) => (
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center font-bold text-sm text-slate-500">
                            {d.uid.charAt(0).toUpperCase()}
                          </div>
                          <span className="font-mono font-bold text-slate-700">{d.uid}</span>
                        </div>
                      )
                    },
                    {
                      header: '操作',
                      accessor: (d) => (
                        <Button type="danger" size="sm" leftIcon="mdi:trash-can-outline" onClick={() => handleRemoveMember(d.uid)}>
                          移除
                        </Button>
                      )
                    }
                  ]}
                />
              )}
            </div>
          </div>
          <HelpText size="L" status="warning">
            管理員注意：強制新增或移除成員將立即生效。該動作會同步更新至資料庫並排入 LDAP 同步佇列。
          </HelpText>
        </div>
      </div>
    </div>
  );
}

export default AliasDetail;

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
  // Handles reordering the list when a drag ends
  const handleDragEnd = (result) => {
    // If dropped outside the list, do nothing
    if (!result.destination) return;

    const sourceIndex = result.source.index;
    const destinationIndex = result.destination.index;

    // If dropped in the exact same spot, do nothing
    if (sourceIndex === destinationIndex) return;

    // Reorder the React state array
    setAllMembers((prevMembers) => {
      const newMembers = Array.from(prevMembers);
      const [movedMember] = newMembers.splice(sourceIndex, 1);
      newMembers.splice(destinationIndex, 0, movedMember);
      return newMembers;
    });
  };
  if (loading) return <div className="flex justify-center p-20"><Loader2 className="animate-spin text-indigo-600" size={40} /></div>;
  return (
    // 1. The outer screen container
    <div className="w-full min-h-screen bg-gray-100 py-8 px-4 flex flex-col gap-6">

      {/* 2. HEADER TIER: Unified White Card Container (using max-w-6xl to match the grid below) */}
      <div className="w-full max-w-6xl mx-auto min-h-[100px] flex flex-row items-center justify-between bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
        
        {/* Left Side: The TitleArea with enlarged text */}
        <div className="flex-1 flex flex-col justify-center h-full [&>*]:!border-none [&_*]:!shadow-none [&_hr]:hidden">
          <PageHeader>
            <PageHeader.TitleArea 
              title={
                <span className="text-3xl sm:text-4xl font-extrabold tracking-tight block leading-tight">
                  別名設定 ({id})
                </span>
              } 
              breadcrumb={
                <span className="text-base sm:text-lg text-slate-500 mt-2 block">
                  首頁 / 別名管理 / 設定
                </span>
              } 
            />
          </PageHeader>
        </div>

        {/* Right Side: The Return Button */}
        <div className="flex-shrink-0 ml-4 flex items-center h-full">
          <Button type="default" size="lg" leftIcon="mdi:arrow-left" onClick={() => navigate('/manage/aliases')}>
            返回清單
          </Button>
        </div>
      </div>

      {/* 3. CONTENT TIER: The Main Grid */}
      <div className="w-full max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8">
        
        {/* ========================================== */}
        {/* LEFT COLUMN (col-span-1): Forms & Inputs     */}
        {/* ========================================== */}
        <div className="md:col-span-1">
          {/* Wrapped in a sticky container so both boxes float nicely as you scroll down the member list */}
          <div className="sticky top-8 flex flex-col gap-6">
            
            {/* Box 1: 基本設定表單 (Basic Info) */}
            <section className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-6">
              <h2 className="text-lg font-bold text-slate-800">基本資訊</h2>
              <form onSubmit={handleUpdateAlias} className="space-y-6">
                <Input 
                  label="顯示名稱"
                  value={alias.display_name || ''}
                  onChange={(val) => setAlias({...alias, display_name: val})}
                />
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

            {/* Box 2: 新增成員 (Add Member - MOVED HERE) */}
            <section className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-6">
              <h2 className="text-lg font-bold text-slate-800">新增成員</h2>
              <form onSubmit={handleAddMember} className="space-y-4">
                <Input 
                  label="成員 UID"
                  placeholder="輸入學生/員工 UID (例如: b13902001)"
                  value={newUid}
                  onChange={(val) => setNewUid(val)}
                  className="w-full"
                />
                <Button type="brand" className="w-full justify-center" leftIcon="mdi:account-plus" onClick={handleAddMember}>
                  加入
                </Button>
              </form>
            </section>
            
          </div>
        </div>

        {/* ========================================== */}
        {/* RIGHT COLUMN (col-span-2): Member List       */}
        {/* ========================================== */}
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            
            {/* Cleaner header since the input was moved out */}
            <div className="p-6 bg-slate-50 border-b border-slate-200">
              <h2 className="text-lg font-bold text-slate-800">成員管理清單</h2>
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
                  draggable
                  onDragEnd={handleDragEnd}
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

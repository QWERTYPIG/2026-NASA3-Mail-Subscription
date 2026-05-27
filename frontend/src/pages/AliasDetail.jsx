import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { UserPlus, ArrowLeft, Loader2, Save, Trash2, Settings, Info } from 'lucide-react';

const AliasDetail = () => {
  const { id } = useParams(); // id is the alias_name
  const navigate = useNavigate();
  const [alias, setAlias] = useState({ display_name: '', description: '' });
  const [allMembers, setAllMembers] = useState([]); // Array of strings (UIDs)
  const [newUid, setNewUid] = useState(''); // State for the add member input
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // 1. 抓取資料
  useEffect(() => { 
    const fetchData = async () => {
      try {
        // Fetch all aliases to get this specific alias's details (since there is no GET single alias endpoint)
        const aliasRes = await api.get('/manage/aliases/');
        const currentAlias = aliasRes.data.find(a => a.alias_name === id);
        
        if (!currentAlias) throw new Error("Alias not found");
        setAlias(currentAlias);

        // Fetch the flat array of string UIDs
        const membersRes = await api.get(`/manage/aliases/${id}/users/`);
        setAllMembers(membersRes.data);
      } catch {
        toast.error("無法載入資料");
        navigate('/manage/aliases/'); 
      } finally {
        setLoading(false);
      }
    };
    fetchData(); 
  }, [id, navigate]);

  // 2. 儲存別名修改 (PATCH)
  const handleUpdateAlias = async (e) => {
    e.preventDefault();
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

  // 3. 手動加入成員 (POST)
  const handleAddMember = async (e) => {
    e.preventDefault();
    if (!newUid.trim()) return;
    
    try {
      await api.post(`/manage/aliases/${id}/users/`, { uid: newUid.trim() });
      toast.success(`已將 ${newUid} 加入群組`);
      setAllMembers(prev => [...prev, newUid.trim()]);
      setNewUid(''); // Clear input
    } catch (err) {
      toast.error(err.response?.data?.error || "加入失敗，請確認 UID 正確");
    }
  };

  // 4. 手動移除成員 (DELETE)
  const handleRemoveMember = async (uidToRemove) => {
    if (!window.confirm(`確定要將 ${uidToRemove} 從此群組移除嗎？`)) return;
    
    try {
      await api.delete(`/manage/aliases/${id}/users/${uidToRemove}/`);
      toast.success(`已移除 ${uidToRemove}`);
      setAllMembers(prev => prev.filter(uid => uid !== uidToRemove));
    } catch {
      toast.error("移除失敗");
    }
  };

  if (loading) return <div className="flex justify-center p-20"><Loader2 className="animate-spin text-indigo-600" size={40} /></div>;

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* 頂部導覽 */}
      <button 
        onClick={() => navigate('/manage/aliases')}
        className="flex items-center gap-2 text-slate-500 hover:text-indigo-600 transition-colors font-medium"
      >
        <ArrowLeft size={18} /> 返回別名清單
      </button>

      <div className="grid md:grid-cols-3 gap-8">
        {/* 左側：基本設定表單 */}
        <div className="md:col-span-1">
          <section className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm sticky top-24">
            <h2 className="text-lg font-bold !text-slate-800 mb-4 flex items-center gap-2">
              <Settings size={18} className="text-indigo-500" /> 別名設定 ({id})
            </h2>
            <form onSubmit={handleUpdateAlias} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-400 uppercase mb-1">顯示名稱</label>
                <input 
                  className="w-full p-2 bg-slate-50 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
                  value={alias.display_name || ''}
                  onChange={(e) => setAlias({...alias, display_name: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-400 uppercase mb-1">描述說明</label>
                <textarea 
                  rows="4"
                  className="w-full p-2 bg-slate-50 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none resize-none"
                  value={alias.description || ''}
                  onChange={(e) => setAlias({...alias, description: e.target.value})}
                />
              </div>
              <button 
                type="submit" 
                disabled={saving}
                className="w-full py-2 bg-indigo-600 text-white rounded-lg font-bold hover:bg-indigo-700 transition-all flex items-center justify-center gap-2"
              >
                {saving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
                {saving ? "儲存中" : "儲存變更"}
              </button>
            </form>
          </section>
        </div>

        {/* 右側：成員管理清單 */}
        <div className="md:col-span-2 space-y-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            {/* 新增成員區塊 */}
            <div className="p-4 bg-slate-50 border-b border-slate-200">
              <form onSubmit={handleAddMember} className="flex gap-2">
                <input 
                  type="text"
                  placeholder="輸入學生/員工 UID (例如: b13902001)"
                  className="flex-1 p-2 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
                  value={newUid}
                  onChange={(e) => setNewUid(e.target.value)}
                />
                <button 
                  type="submit"
                  className="px-4 py-2 bg-indigo-50 text-indigo-700 font-bold rounded-lg border border-indigo-200 hover:bg-indigo-100 transition-colors flex items-center gap-2"
                >
                  <UserPlus size={16} /> 加入
                </button>
              </form>
            </div>

            {/* 成員列表 */}
            <ul className="divide-y divide-slate-100 max-h-[500px] overflow-y-auto">
              {allMembers.length === 0 ? (
                <li className="p-8 text-center text-slate-400">目前無訂閱成員</li>
              ) : (
                allMembers.map(uid => (
                  <li key={uid} className="p-4 flex items-center justify-between hover:bg-slate-50">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center font-bold text-sm text-slate-500">
                        {uid.charAt(0).toUpperCase()}
                      </div>
                      <p className="font-bold text-slate-700 font-mono">{uid}</p>
                    </div>

                    <button 
                      onClick={() => handleRemoveMember(uid)}
                      className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="移除成員"
                    >
                      <Trash2 size={18} />
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>

          <div className="p-4 bg-amber-50 border border-amber-100 rounded-xl flex items-start gap-3">
            <Info className="text-amber-500 shrink-0 mt-0.5" size={18} />
            <p className="text-xs text-amber-700 leading-relaxed">
              <b>管理員注意：</b> 強制新增或移除成員將立即生效。該動作會同步更新至資料庫並排入 LDAP 同步佇列。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AliasDetail;

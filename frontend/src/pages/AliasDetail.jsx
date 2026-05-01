import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { Mail, UserMinus, ArrowLeft, Loader2, Save, Users, Trash2, Settings, Info} from 'lucide-react';

const AliasDetail = () => {
	const { id } = useParams();
	const navigate = useNavigate();
	const [alias, setAlias] = useState(null);
	const [allMembers, setAllMembers] = useState([]);
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);

	// 1. 抓取資料 (別名詳情 + 訂閱成員)

	useEffect(() => { 
		const fetchData = async () => {
			try {
				const aliasRes = await api.get(`/admin/aliases/${id}`);
				setAlias(aliasRes.data);
				setAllMembers(aliasRes.data.members);
			} catch {
				toast.error("無法載入資料");
				navigate('/admin/aliases'); // 失敗則退回列表
			} finally {
				setLoading(false);
			}
		};
		fetchData(); 
	}, [id, navigate]);

	// 2. 儲存別名修改 (名稱與描述)
	const handleUpdateAlias = async (e) => {
		e.preventDefault();
		setSaving(true);
		try {
			await api.patch(`/admin/aliases/${id}`, alias);
			toast.success("更新成功");
		} catch {
			toast.error("更新失敗");
		} finally {
			setSaving(false);
		}
	};

	const handleToggleSubscription = async (userId, currentStatus) => {
		const action = currentStatus === 1 ? 'unsub' : 'sub';

		try {
			// 呼叫我們之前定義的管理員訂閱 API
			await api.post(`/admin/aliases/${id}/subscriptions`, {
				user_id: userId,
				action: action
			});

			// 成功後，手動更新前端 State，避免重新 Fetch 整個頁面 (Optimistic Update)
			setAllMembers(prev => prev.map(member =>
				member.id === userId
				? { ...member, is_subscribed: currentStatus === 1 ? 0 : 1 }
				: member
			));

			toast.success(action === 'sub' ? "已加入訂閱" : "已移除訂閱");
		} catch {
			toast.error("操作失敗");
		}
	};

	if (loading) return <div className="flex justify-center p-20"><Loader2 className="animate-spin text-indigo-600" size={40} /></div>;

	return (
		<div className="max-w-4xl mx-auto space-y-8">
		{/* 頂部導覽 */}
		<button 
		onClick={() => navigate('/admin/aliases')}
		className="flex items-center gap-2 text-slate-500 hover:text-indigo-600 transition-colors font-medium"
		>
		<ArrowLeft size={18} /> 返回別名清單
		</button>

		<div className="grid md:grid-cols-3 gap-8">
		{/* 左側：基本設定表單 */}
		<div className="md:col-span-1">
		<section className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm sticky top-24">
		<h2 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
		<Settings size={18} className="text-indigo-500" /> 別名設定
		</h2>
		<form onSubmit={handleUpdateAlias} className="space-y-4">
		<div>
		<label className="block text-xs font-bold text-slate-400 uppercase mb-1">別名名稱</label>
		<input 
		className="w-full p-2 bg-slate-50 border rounded-lg font-mono text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
		value={alias.name}
		onChange={(e) => setAlias({...alias, name: e.target.value})}
		/>
		</div>
		<div>
		<label className="block text-xs font-bold text-slate-400 uppercase mb-1">描述說明</label>
		<textarea 
		rows="3"
		className="w-full p-2 bg-slate-50 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
		value={alias.description}
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
		<ul className="divide-y divide-slate-100">
		{allMembers.map(member => (
			<li key={member.id} className="p-4 flex items-center justify-between hover:bg-slate-50">
			<div className="flex items-center gap-3">
			<div className={`w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm ${
				member.is_subscribed ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-400'
			}`}>
			{member.username.charAt(0).toUpperCase()}
			</div>
			<div className="flex flex-col items-start text-left">
			<p className="font-bold text-slate-700">{member.username}</p>
			<p className="text-xs text-slate-400 font-mono">ID: {member.id}</p>
			</div>
			</div>

			{/* Toggle 按鈕 */}
			<button 
			onClick={() => handleToggleSubscription(member.id, member.is_subscribed)}
			className={`px-4 py-1.5 rounded-lg text-sm font-bold transition-all ${
				member.is_subscribed 
					? 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200' 
					: 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-200'
			}`}
			>
			{member.is_subscribed ? '移除成員' : '加入成員'}
			</button>
			</li>
		))}
		</ul>


		<div className="p-4 bg-amber-50 border border-amber-100 rounded-xl flex items-start gap-3">
		<Info className="text-amber-500 shrink-0 mt-0.5" size={18} />
		<p className="text-xs text-amber-700 leading-relaxed">
		<b>管理員注意：</b> 強制移除成員將立即停止該使用者接收發往此別名的郵件。該動作會同步更新至資料庫的 <code>subscriptions</code> 關聯表。
		</p>
		</div>
		</div>
		</div>
	);
}

export default AliasDetail;

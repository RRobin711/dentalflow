interface LayoutProps {
  view: string;
  onNavigate: (view: any) => void;
  sseConnected: boolean;
}

const NAV_ITEMS = [
  { id: 'claims', label: 'Claims', icon: '📋' },
  { id: 'new-claim', label: 'New Claim', icon: '➕' },
  { id: 'eligibility', label: 'Eligibility', icon: '🔍' },
  { id: 'health', label: 'System', icon: '💚' },
];

export function Layout({ view, onNavigate, sseConnected }: LayoutProps) {
  return (
    <nav className="w-48 bg-white border-r border-slate-200 flex flex-col min-h-screen">
      <div className="p-4 border-b border-slate-200">
        <h1 className="font-mono font-bold text-lg text-teal-700 tracking-tight">DentalFlow</h1>
        <p className="text-xs text-slate-500 mt-0.5">Claims Pipeline</p>
      </div>
      <div className="flex-1 py-2">
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full text-left px-4 py-2.5 text-sm flex items-center gap-2.5 transition-colors ${
              view === item.id
                ? 'bg-teal-700 text-white font-medium'
                : 'text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span className="text-base">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </div>
      <div className="p-4 border-t border-slate-200">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className={`inline-block w-2 h-2 rounded-full ${sseConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          SSE {sseConnected ? 'Connected' : 'Disconnected'}
        </div>
      </div>
    </nav>
  );
}

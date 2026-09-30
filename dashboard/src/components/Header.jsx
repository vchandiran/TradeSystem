import React, { useState } from 'react';
import { 
  Play, 
  Pause, 
  ShieldAlert, 
  Activity, 
  Radio, 
  BarChart2, 
  AlertTriangle, 
  CheckCircle2,
  Clock
} from 'lucide-react';

export default function Header({ 
  telemetry, 
  onToggleEngine, 
  onSquareOffAll, 
  onOpenBacktest 
}) {
  const [confirmKill, setConfirmKill] = useState(false);

  const isRunning = telemetry?.engine_running ?? true;
  const isConnected = telemetry?.broker_connected ?? true;
  const isMarketOpen = telemetry?.market_open ?? false;
  const mode = telemetry?.mode ?? 'paper';

  const handleSquareOffClick = () => {
    if (!confirmKill) {
      setConfirmKill(true);
      setTimeout(() => setConfirmKill(false), 4000);
    } else {
      onSquareOffAll();
      setConfirmKill(false);
    }
  };

  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '12px 24px',
      background: 'rgba(15, 23, 42, 0.85)',
      backdropFilter: 'blur(12px)',
      borderBottom: '1px solid #1e293b',
      position: 'sticky',
      top: 0,
      zIndex: 50,
      flexWrap: 'wrap',
      gap: '12px'
    }}>
      {/* Brand & Market Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '8px',
            background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 'bold',
            fontSize: '18px',
            boxShadow: '0 0 15px rgba(16, 185, 129, 0.35)'
          }}>
            ⚡
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '16px', letterSpacing: '-0.3px', color: '#f8fafc' }}>
              NSE ALICE BLUE <span style={{ color: '#10b981', fontSize: '12px', fontWeight: 600, padding: '2px 6px', background: 'rgba(16, 185, 129, 0.15)', borderRadius: '4px', marginLeft: '6px' }}>70%+ WIN DESK</span>
            </div>
            <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>Exchange: NSE India</span>
              <span>•</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Clock size={11} />
                09:15 - 15:30 IST
              </span>
            </div>
          </div>
        </div>

        {/* NSE Market Status Badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 10px',
          borderRadius: '20px',
          background: isMarketOpen ? 'rgba(16, 185, 129, 0.15)' : 'rgba(148, 163, 184, 0.1)',
          border: `1px solid ${isMarketOpen ? 'rgba(16, 185, 129, 0.3)' : 'rgba(148, 163, 184, 0.2)'}`,
          fontSize: '11px',
          fontWeight: 600,
          color: isMarketOpen ? '#10b981' : '#94a3b8'
        }}>
          <span style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            background: isMarketOpen ? '#10b981' : '#64748b',
            boxShadow: isMarketOpen ? '0 0 8px #10b981' : 'none'
          }} />
          {isMarketOpen ? 'NSE MARKET OPEN' : 'NSE CLOSED (SIM ACTIVE)'}
        </div>

        {/* Data Feed Source Badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 10px',
          borderRadius: '20px',
          background: telemetry?.data_source === 'ALICE_BLUE_LIVE' 
            ? 'rgba(16, 185, 129, 0.15)' 
            : (telemetry?.data_source === 'NSE_LIVE_MARKET' ? 'rgba(56, 189, 248, 0.15)' : 'rgba(245, 158, 11, 0.12)'),
          border: `1px solid ${
            telemetry?.data_source === 'ALICE_BLUE_LIVE' 
              ? 'rgba(16, 185, 129, 0.4)' 
              : (telemetry?.data_source === 'NSE_LIVE_MARKET' ? 'rgba(56, 189, 248, 0.4)' : 'rgba(245, 158, 11, 0.3)')
          }`,
          fontSize: '11px',
          fontWeight: 700,
          color: telemetry?.data_source === 'ALICE_BLUE_LIVE' 
            ? '#10b981' 
            : (telemetry?.data_source === 'NSE_LIVE_MARKET' ? '#38bdf8' : '#fbbf24')
        }}>
          <span style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            background: telemetry?.data_source === 'ALICE_BLUE_LIVE' 
              ? '#10b981' 
              : (telemetry?.data_source === 'NSE_LIVE_MARKET' ? '#38bdf8' : '#f59e0b'),
            boxShadow: '0 0 8px currentColor'
          }} />
          {telemetry?.data_source === 'ALICE_BLUE_LIVE'
            ? 'ALICE BLUE LIVE (TICK-BY-TICK)'
            : (telemetry?.data_source === 'NSE_LIVE_MARKET' ? 'REAL NSE LIVE MARKET FEED' : 'SIMULATED DATA')}
        </div>

        {/* Trading Mode Badge */}
        <div style={{
          padding: '4px 10px',
          borderRadius: '20px',
          background: mode === 'live' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.15)',
          border: `1px solid ${mode === 'live' ? 'rgba(239, 68, 68, 0.4)' : 'rgba(245, 158, 11, 0.3)'}`,
          fontSize: '11px',
          fontWeight: 700,
          color: mode === 'live' ? '#ef4444' : '#fbbf24'
        }}>
          {mode === 'live' ? 'LIVE (REAL MONEY)' : 'PAPER SIMULATOR'}
        </div>
      </div>

      {/* Control Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* Backtest Report Button */}
        <button
          onClick={onOpenBacktest}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 14px',
            borderRadius: '6px',
            background: '#1e293b',
            color: '#f8fafc',
            border: '1px solid #334155',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
          onMouseEnter={(e) => e.currentTarget.style.background = '#334155'}
          onMouseLeave={(e) => e.currentTarget.style.background = '#1e293b'}
        >
          <BarChart2 size={14} color="#60a5fa" />
          70% Win Backtest Report
        </button>

        {/* Engine Toggle */}
        <button
          onClick={onToggleEngine}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 14px',
            borderRadius: '6px',
            background: isRunning ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            color: isRunning ? '#f59e0b' : '#10b981',
            border: `1px solid ${isRunning ? 'rgba(245, 158, 11, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`,
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
        >
          {isRunning ? <Pause size={14} /> : <Play size={14} />}
          {isRunning ? 'Pause Engine' : 'Resume Engine'}
        </button>

        {/* Emergency Kill Switch */}
        <button
          onClick={handleSquareOffClick}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 14px',
            borderRadius: '6px',
            background: confirmKill ? '#ef4444' : 'rgba(239, 68, 68, 0.15)',
            color: confirmKill ? '#fff' : '#f87171',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'all 0.2s',
            boxShadow: confirmKill ? '0 0 15px rgba(239, 68, 68, 0.5)' : 'none'
          }}
        >
          <ShieldAlert size={15} />
          {confirmKill ? 'CLICK TO CONFIRM SQUARE OFF!' : 'SQUARE OFF ALL'}
        </button>
      </div>
    </header>
  );
}

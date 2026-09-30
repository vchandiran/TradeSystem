import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import KpiCards from './components/KpiCards';
import WatchlistPanel from './components/WatchlistPanel';
import SignalMonitor from './components/SignalMonitor';
import PositionsTable from './components/PositionsTable';
import OrderHistory from './components/OrderHistory';
import OrderDesk from './components/OrderDesk';
import BacktestModal from './components/BacktestModal';

export default function App() {
  const [telemetry, setTelemetry] = useState(null);
  const [selectedSymbol, setSelectedSymbol] = useState('RELIANCE');
  const [isBacktestOpen, setIsBacktestOpen] = useState(false);
  const wsRef = useRef(null);

  // Initialize WebSocket with auto-reconnect
  useEffect(() => {
    let reconnectTimeout;

    const connectWebSocket = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WS] Connected to live trading telemetry stream');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setTelemetry(data);
        } catch (e) {
          console.error('[WS] Parse error:', e);
        }
      };

      ws.onclose = () => {
        console.warn('[WS] Stream closed. Reconnecting in 2s...');
        reconnectTimeout = setTimeout(connectWebSocket, 2000);
      };

      ws.onerror = (err) => {
        console.error('[WS] Error:', err);
        ws.close();
      };
    };

    connectWebSocket();

    // Initial REST fallback fetch
    fetch('/api/status')
      .then(res => res.json())
      .then(status => {
        setTelemetry(prev => ({ ...prev, ...status }));
      })
      .catch(() => {});

    return () => {
      clearTimeout(reconnectTimeout);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  // Handlers
  const handleToggleEngine = async () => {
    try {
      const res = await fetch('/api/engine/toggle', { method: 'POST' });
      const data = await res.json();
      setTelemetry(prev => prev ? { ...prev, engine_running: data.engine_running } : null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSquareOffAll = async () => {
    try {
      await fetch('/api/positions/square-off-all', { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
  };

  const handleSquareOffPosition = async (symbol) => {
    try {
      await fetch(`/api/positions/square-off/${symbol}`, { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
  };

  const handlePlaceOrder = async (orderData) => {
    try {
      const res = await fetch('/api/orders/place', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(orderData)
      });
      return await res.json();
    } catch (e) {
      console.error(e);
    }
  };

  const currentStockData = telemetry?.watchlist?.find(x => x.symbol === selectedSymbol) || 
    telemetry?.watchlist?.[0] || { symbol: selectedSymbol, ltp: 1192.90, change_pct: 0.92 };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#080c14' }}>
      {/* Top Navigation */}
      <Header
        telemetry={telemetry}
        onToggleEngine={handleToggleEngine}
        onSquareOffAll={handleSquareOffAll}
        onOpenBacktest={() => setIsBacktestOpen(true)}
      />

      {/* Main Trading Floor */}
      <main style={{ flex: 1, padding: '16px 24px' }}>
        {/* KPI Row */}
        <KpiCards
          pnl={telemetry?.pnl}
          positionsCount={telemetry?.positions?.length}
        />

        {/* 3-Column Trading Terminal Grid */}
        <div className="dashboard-grid">
          {/* Column 1: Watchlist & Search */}
          <div style={{ height: 'calc(100vh - 250px)', minHeight: '520px' }}>
            <WatchlistPanel
              watchlist={telemetry?.watchlist}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={setSelectedSymbol}
            />
          </div>

          {/* Column 2: 70%+ Strategy Monitor, Open Positions & Orders */}
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <SignalMonitor
              confluence={telemetry?.confluence}
              selectedSymbol={selectedSymbol}
              stockData={currentStockData}
            />
            <PositionsTable
              positions={telemetry?.positions}
              onSquareOffPosition={handleSquareOffPosition}
            />
            <OrderHistory
              orders={telemetry?.orders}
            />
          </div>

          {/* Column 3: Manual Execution Desk */}
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <OrderDesk
              selectedSymbol={selectedSymbol}
              stockData={currentStockData}
              onPlaceOrder={handlePlaceOrder}
            />
          </div>
        </div>
      </main>

      {/* Backtest Verification Modal */}
      <BacktestModal
        isOpen={isBacktestOpen}
        onClose={() => setIsBacktestOpen(false)}
      />
    </div>
  );
}

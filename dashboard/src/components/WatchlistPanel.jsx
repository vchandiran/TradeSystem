import React, { useState } from 'react';
import { Search, TrendingUp, TrendingDown } from 'lucide-react';

export default function WatchlistPanel({ watchlist, selectedSymbol, onSelectSymbol }) {
  const [searchTerm, setSearchTerm] = useState('');

  const items = watchlist || [];
  const filtered = items.filter(item => 
    item.symbol.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (item.name && item.name.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderRadius: '10px',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden'
    }}>
      {/* Header & Search */}
      <div style={{ padding: '14px 16px', borderBottom: '1px solid #1e293b' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.2px' }}>
            NSE WATCHLIST
          </span>
          <span style={{ fontSize: '11px', color: '#64748b' }}>
            {filtered.length} Symbols
          </span>
        </div>
        <div style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center'
        }}>
          <Search size={14} color="#64748b" style={{ position: 'absolute', left: '10px' }} />
          <input
            type="text"
            placeholder="Search NSE symbols..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '6px 10px 6px 30px',
              background: '#080c14',
              border: '1px solid #1e293b',
              borderRadius: '6px',
              color: '#f8fafc',
              fontSize: '12px',
              outline: 'none'
            }}
          />
        </div>
      </div>

      {/* Stock List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.map((stock) => {
          const isSelected = selectedSymbol === stock.symbol;
          const isUp = stock.change_pct >= 0;

          return (
            <div
              key={stock.symbol}
              onClick={() => onSelectSymbol(stock.symbol)}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 16px',
                borderBottom: '1px solid #131b2e',
                background: isSelected ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                borderLeft: isSelected ? '3px solid #3b82f6' : '3px solid transparent',
                cursor: 'pointer',
                transition: 'background 0.15s ease'
              }}
              onMouseEnter={(e) => {
                if (!isSelected) e.currentTarget.style.background = '#141f38';
              }}
              onMouseLeave={(e) => {
                if (!isSelected) e.currentTarget.style.background = 'transparent';
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontWeight: 700, fontSize: '13px', color: '#f8fafc' }}>
                    {stock.symbol}
                  </span>
                  <span style={{ fontSize: '9px', padding: '1px 4px', borderRadius: '3px', background: '#1e293b', color: '#94a3b8' }}>
                    EQ
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px', maxWidth: '140px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {stock.name || stock.symbol}
                </div>
              </div>

              <div style={{ textAlign: 'right' }}>
                <div className="mono" style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>
                  ₹{(Number(stock.ltp) || 0).toFixed(2)}
                </div>
                <div style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: isUp ? '#10b981' : '#ef4444',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  gap: '2px',
                  marginTop: '2px'
                }}>
                  {isUp ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                  {isUp ? '+' : ''}{(Number(stock.change_pct) || 0).toFixed(2)}%
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

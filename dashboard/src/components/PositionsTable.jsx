import React from 'react';
import { Layers, ArrowUpRight, ArrowDownRight, XCircle } from 'lucide-react';

export default function PositionsTable({ positions, onSquareOffPosition }) {
  const items = positions || [];

  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderRadius: '10px',
      overflow: 'hidden',
      marginBottom: '16px'
    }}>
      {/* Title */}
      <div style={{
        padding: '14px 16px',
        borderBottom: '1px solid #1e293b',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Layers size={16} color="#38bdf8" />
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
            OPEN INTRADAY POSITIONS
          </span>
          <span style={{
            fontSize: '11px',
            padding: '1px 6px',
            borderRadius: '10px',
            background: '#1e293b',
            color: '#94a3b8'
          }}>
            {items.length}
          </span>
        </div>
        <span style={{ fontSize: '11px', color: '#64748b' }}>
          Product: MIS • Auto Square-off at 15:10 IST
        </span>
      </div>

      {/* Table */}
      {items.length === 0 ? (
        <div style={{ padding: '32px', textAlign: 'center', color: '#64748b', fontSize: '12px' }}>
          No active positions. Trading engine is scanning for 70%+ confluence setups...
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
            <thead>
              <tr style={{ background: '#080c14', color: '#64748b', fontSize: '11px', textTransform: 'uppercase' }}>
                <th style={{ padding: '10px 14px' }}>Symbol</th>
                <th style={{ padding: '10px 14px' }}>Side</th>
                <th style={{ padding: '10px 14px' }}>Qty</th>
                <th style={{ padding: '10px 14px' }}>Entry Price</th>
                <th style={{ padding: '10px 14px' }}>LTP</th>
                <th style={{ padding: '10px 14px' }}>Stop Loss</th>
                <th style={{ padding: '10px 14px' }}>Target</th>
                <th style={{ padding: '10px 14px' }}>Unrealized P&L</th>
                <th style={{ padding: '10px 14px', textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((pos) => {
                const isBuy = pos.side === 'BUY';
                const isProfitable = (pos.unrealized_pnl ?? 0) >= 0;

                return (
                  <tr
                    key={pos.symbol}
                    style={{
                      borderBottom: '1px solid #131b2e',
                      transition: 'background 0.15s ease'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.background = '#141f38'}
                    onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                  >
                    <td style={{ padding: '12px 14px', fontWeight: 700, color: '#f8fafc' }}>
                      {pos.symbol}
                    </td>
                    <td style={{ padding: '12px 14px' }}>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '3px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 700,
                        background: isBuy ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                        color: isBuy ? '#10b981' : '#ef4444'
                      }}>
                        {isBuy ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                        {pos.side}
                      </span>
                    </td>
                    <td className="mono" style={{ padding: '12px 14px', color: '#cbd5e1' }}>
                      {pos.quantity}
                    </td>
                    <td className="mono" style={{ padding: '12px 14px', color: '#cbd5e1' }}>
                      ₹{pos.entry_price.toFixed(2)}
                    </td>
                    <td className="mono" style={{ padding: '12px 14px', fontWeight: 600, color: '#f8fafc' }}>
                      ₹{pos.current_price.toFixed(2)}
                    </td>
                    <td className="mono" style={{ padding: '12px 14px', color: '#f87171' }}>
                      ₹{pos.stop_loss.toFixed(2)}
                    </td>
                    <td className="mono" style={{ padding: '12px 14px', color: '#34d399' }}>
                      ₹{pos.target.toFixed(2)}
                    </td>
                    <td className="mono" style={{ padding: '12px 14px', fontWeight: 700, color: isProfitable ? '#10b981' : '#ef4444' }}>
                      {isProfitable ? '+' : ''}₹{pos.unrealized_pnl.toFixed(2)}
                      <span style={{ fontSize: '10px', marginLeft: '4px', fontWeight: 500 }}>
                        ({isProfitable ? '+' : ''}{pos.pnl_pct.toFixed(2)}%)
                      </span>
                    </td>
                    <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                      <button
                        onClick={() => onSquareOffPosition(pos.symbol)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: '4px',
                          background: 'rgba(239, 68, 68, 0.12)',
                          color: '#ef4444',
                          border: '1px solid rgba(239, 68, 68, 0.3)',
                          fontSize: '11px',
                          fontWeight: 600,
                          cursor: 'pointer',
                          transition: 'all 0.15s ease'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = '#ef4444';
                          e.currentTarget.style.color = '#fff';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'rgba(239, 68, 68, 0.12)';
                          e.currentTarget.style.color = '#ef4444';
                        }}
                      >
                        Exit
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

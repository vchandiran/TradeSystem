import React from 'react';
import { History, CheckCircle2, Clock, XCircle, TrendingUp, TrendingDown } from 'lucide-react';

export default function OrderHistory({ orders }) {
  const items = orders || [];

  // Summary calculations
  const completedWithProfit = items.filter(o => o.profit !== undefined && o.profit !== null && o.profit !== 0);
  const totalRealizedProfit = items
    .filter(o => o.status === 'COMPLETED' && o.profit !== undefined && o.profit !== null)
    .reduce((sum, o) => sum + Number(o.profit), 0);

  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderRadius: '10px',
      overflow: 'hidden'
    }}>
      {/* Title & Live Summary */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #1e293b',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '8px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <History size={16} color="#38bdf8" />
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.2px' }}>
            ORDER & TRADE EXECUTION HISTORY
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {completedWithProfit.length > 0 && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '3px 8px',
              borderRadius: '6px',
              background: totalRealizedProfit >= 0 ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
              border: totalRealizedProfit >= 0 ? '1px solid rgba(16, 185, 129, 0.25)' : '1px solid rgba(239, 68, 68, 0.25)',
              fontSize: '11px',
              fontWeight: 700,
              color: totalRealizedProfit >= 0 ? '#10b981' : '#ef4444'
            }}>
              <span>Trade P&L:</span>
              <span className="mono">
                {totalRealizedProfit >= 0 ? '+' : ''}₹{totalRealizedProfit.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          )}
          <span style={{ fontSize: '11px', color: '#64748b' }}>
            {items.length} orders
          </span>
        </div>
      </div>

      {/* Table */}
      {items.length === 0 ? (
        <div style={{ padding: '28px', textAlign: 'center', color: '#64748b', fontSize: '12px' }}>
          No orders placed yet today.
        </div>
      ) : (
        <div style={{ maxHeight: '280px', overflowY: 'auto', overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '11px', minWidth: '680px' }}>
            <thead>
              <tr style={{ background: '#080c14', color: '#64748b', textTransform: 'uppercase', fontSize: '10px', letterSpacing: '0.3px' }}>
                <th style={{ padding: '9px 12px' }}>Order ID</th>
                <th style={{ padding: '9px 12px' }}>Time</th>
                <th style={{ padding: '9px 12px' }}>Symbol</th>
                <th style={{ padding: '9px 12px' }}>Side</th>
                <th style={{ padding: '9px 12px' }}>Qty</th>
                <th style={{ padding: '9px 12px' }}>Buy Price</th>
                <th style={{ padding: '9px 12px' }}>Sell Price</th>
                <th style={{ padding: '9px 12px', textAlign: 'right' }}>Profit / P&L</th>
                <th style={{ padding: '9px 12px', textAlign: 'right' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((ord) => {
                const isBuy = ord.side === 'BUY';
                const isCompleted = ord.status === 'COMPLETED';
                const isOpen = ord.status === 'OPEN';

                // Resolve Buy Price
                const buyPriceVal = ord.buy_price !== undefined && ord.buy_price !== null 
                  ? Number(ord.buy_price) 
                  : (isBuy ? Number(ord.price) : null);

                // Resolve Sell Price
                const sellPriceVal = ord.sell_price !== undefined && ord.sell_price !== null 
                  ? Number(ord.sell_price) 
                  : (!isBuy ? Number(ord.price) : null);

                // Resolve Profit
                const hasProfit = ord.profit !== undefined && ord.profit !== null;
                const profitVal = hasProfit ? Number(ord.profit) : null;
                const profitPct = ord.profit_pct !== undefined && ord.profit_pct !== null ? Number(ord.profit_pct) : 0;
                const isWin = profitVal !== null && profitVal >= 0;

                return (
                  <tr
                    key={ord.order_id}
                    style={{ borderBottom: '1px solid #131b2e', transition: 'background 0.15s ease' }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = '#141f38'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <td className="mono" style={{ padding: '9px 12px', color: '#64748b' }}>
                      {ord.order_id}
                    </td>
                    <td style={{ padding: '9px 12px', color: '#94a3b8' }}>
                      {ord.timestamp}
                    </td>
                    <td style={{ padding: '9px 12px', fontWeight: 700, color: '#f8fafc' }}>
                      {ord.symbol}
                    </td>
                    <td style={{ padding: '9px 12px' }}>
                      <span style={{
                        padding: '2px 6px',
                        borderRadius: '3px',
                        fontSize: '10px',
                        fontWeight: 700,
                        background: isBuy ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                        color: isBuy ? '#10b981' : '#ef4444'
                      }}>
                        {ord.side}
                      </span>
                    </td>
                    <td className="mono" style={{ padding: '9px 12px', color: '#cbd5e1' }}>
                      {ord.quantity}
                    </td>
                    <td className="mono" style={{ padding: '9px 12px', color: '#cbd5e1', fontWeight: 600 }}>
                      {buyPriceVal !== null ? `₹${buyPriceVal.toFixed(2)}` : '—'}
                    </td>
                    <td className="mono" style={{ padding: '9px 12px', color: '#cbd5e1', fontWeight: 600 }}>
                      {sellPriceVal !== null ? (
                        <span>
                          ₹{sellPriceVal.toFixed(2)}
                          {isOpen && <span style={{ fontSize: '9px', color: '#94a3b8', marginLeft: '3px' }}>(LTP)</span>}
                        </span>
                      ) : '—'}
                    </td>
                    <td style={{ padding: '9px 12px', textAlign: 'right' }}>
                      {profitVal !== null ? (
                        <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                          <span className="mono" style={{
                            fontSize: '11px',
                            fontWeight: 700,
                            color: isWin ? '#10b981' : '#ef4444',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}>
                            {isWin ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                            {isWin ? '+' : ''}₹{profitVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                          <span style={{
                            fontSize: '9px',
                            color: isWin ? '#34d399' : '#f87171',
                            fontWeight: 600
                          }}>
                            {isWin ? '+' : ''}{profitPct.toFixed(2)}%
                            {isOpen && ' (Unrealized)'}
                          </span>
                        </div>
                      ) : (
                        <span style={{ color: '#64748b' }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: '9px 12px', textAlign: 'right' }}>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '3px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 600,
                        background: isCompleted 
                          ? 'rgba(16, 185, 129, 0.12)' 
                          : isOpen 
                            ? 'rgba(59, 130, 246, 0.15)' 
                            : 'rgba(239, 68, 68, 0.12)',
                        color: isCompleted ? '#34d399' : isOpen ? '#38bdf8' : '#f87171'
                      }}>
                        {isCompleted ? <CheckCircle2 size={10} /> : isOpen ? <Clock size={10} /> : <XCircle size={10} />}
                        {ord.status}
                      </span>
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

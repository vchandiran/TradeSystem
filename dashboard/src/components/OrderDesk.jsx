import React, { useState, useEffect } from 'react';
import { Send, DollarSign, Shield, Zap } from 'lucide-react';

export default function OrderDesk({ selectedSymbol, stockData, onPlaceOrder }) {
  const [side, setSide] = useState('BUY');
  const [quantity, setQuantity] = useState(25);
  const [orderType, setOrderType] = useState('Market');
  const [price, setPrice] = useState(stockData?.ltp ?? 2850.40);
  const [productType, setProductType] = useState('Intraday (MIS)');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (stockData?.ltp) {
      setPrice(stockData.ltp);
    }
  }, [stockData, selectedSymbol]);

  const ltp = stockData?.ltp ?? 2850.40;
  const execPrice = orderType === 'Market' ? ltp : price;
  const orderValue = execPrice * quantity;
  const marginRequired = productType.includes('MIS') ? orderValue / 5 : orderValue; // 5x leverage

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onPlaceOrder({
        symbol: selectedSymbol || 'RELIANCE',
        side,
        quantity: parseInt(quantity, 10),
        order_type: orderType,
        price: parseFloat(execPrice),
        product_type: productType,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderRadius: '10px',
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      gap: '14px'
    }}>
      {/* Title */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
          MANUAL ORDER DESK
        </span>
        <span style={{
          fontSize: '11px',
          fontWeight: 700,
          padding: '2px 6px',
          borderRadius: '4px',
          background: '#1e293b',
          color: '#38bdf8'
        }}>
          {selectedSymbol || 'RELIANCE'}
        </span>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {/* BUY / SELL Switcher */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '8px',
          background: '#080c14',
          padding: '4px',
          borderRadius: '8px'
        }}>
          <button
            type="button"
            onClick={() => setSide('BUY')}
            style={{
              padding: '8px',
              borderRadius: '6px',
              border: 'none',
              background: side === 'BUY' ? '#10b981' : 'transparent',
              color: side === 'BUY' ? '#fff' : '#94a3b8',
              fontWeight: 700,
              fontSize: '12px',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            BUY
          </button>
          <button
            type="button"
            onClick={() => setSide('SELL')}
            style={{
              padding: '8px',
              borderRadius: '6px',
              border: 'none',
              background: side === 'SELL' ? '#ef4444' : 'transparent',
              color: side === 'SELL' ? '#fff' : '#94a3b8',
              fontWeight: 700,
              fontSize: '12px',
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            SELL
          </button>
        </div>

        {/* Quantity Selection */}
        <div>
          <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>
            Quantity (Shares)
          </label>
          <input
            type="number"
            min="1"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 10px',
              background: '#080c14',
              border: '1px solid #1e293b',
              borderRadius: '6px',
              color: '#f8fafc',
              fontSize: '13px',
              fontWeight: 600,
              outline: 'none'
            }}
          />
          <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
            {[10, 25, 50, 100].map((qty) => (
              <button
                key={qty}
                type="button"
                onClick={() => setQuantity(qty)}
                style={{
                  flex: 1,
                  padding: '4px',
                  background: quantity === qty ? '#334155' : '#1e293b',
                  border: 'none',
                  borderRadius: '4px',
                  color: quantity === qty ? '#f8fafc' : '#94a3b8',
                  fontSize: '10px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                {qty}
              </button>
            ))}
          </div>
        </div>

        {/* Order Type & Product */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>
              Order Type
            </label>
            <select
              value={orderType}
              onChange={(e) => setOrderType(e.target.value)}
              style={{
                width: '100%',
                padding: '8px',
                background: '#080c14',
                border: '1px solid #1e293b',
                borderRadius: '6px',
                color: '#f8fafc',
                fontSize: '12px',
                outline: 'none'
              }}
            >
              <option value="Market">Market</option>
              <option value="Limit">Limit</option>
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>
              Product
            </label>
            <select
              value={productType}
              onChange={(e) => setProductType(e.target.value)}
              style={{
                width: '100%',
                padding: '8px',
                background: '#080c14',
                border: '1px solid #1e293b',
                borderRadius: '6px',
                color: '#f8fafc',
                fontSize: '12px',
                outline: 'none'
              }}
            >
              <option value="Intraday (MIS)">MIS (5x Intraday)</option>
              <option value="Delivery (CNC)">CNC (Delivery)</option>
            </select>
          </div>
        </div>

        {/* Limit Price Input if Limit Order */}
        {orderType === 'Limit' && (
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>
              Limit Price (₹)
            </label>
            <input
              type="number"
              step="0.05"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 10px',
                background: '#080c14',
                border: '1px solid #1e293b',
                borderRadius: '6px',
                color: '#f8fafc',
                fontSize: '13px',
                fontWeight: 600,
                outline: 'none'
              }}
            />
          </div>
        )}

        {/* Financial Summary */}
        <div style={{
          padding: '10px',
          borderRadius: '6px',
          background: '#080c14',
          border: '1px solid #131b2e',
          fontSize: '11px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', color: '#94a3b8' }}>
            <span>Order Value:</span>
            <span className="mono" style={{ color: '#f8fafc' }}>₹{orderValue.toFixed(2)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
            <span>Margin Required (5x):</span>
            <span className="mono" style={{ color: '#38bdf8', fontWeight: 700 }}>₹{marginRequired.toFixed(2)}</span>
          </div>
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isSubmitting}
          style={{
            padding: '12px',
            borderRadius: '6px',
            border: 'none',
            background: side === 'BUY' ? '#10b981' : '#ef4444',
            color: '#fff',
            fontWeight: 700,
            fontSize: '13px',
            cursor: isSubmitting ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            boxShadow: side === 'BUY' ? '0 0 15px rgba(16, 185, 129, 0.35)' : '0 0 15px rgba(239, 68, 68, 0.35)',
            transition: 'all 0.15s ease'
          }}
        >
          <Send size={15} />
          {isSubmitting ? 'Placing Order...' : `${side} ${quantity} ${selectedSymbol || 'RELIANCE'}`}
        </button>
      </form>
    </div>
  );
}

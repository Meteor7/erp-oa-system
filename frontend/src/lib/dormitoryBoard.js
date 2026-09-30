// 宿舍看板的显示规则（与 demo 一致），纯函数便于测试。
// 颜色压低饱和度：蓝 = 公司承担 / 入住，沙色 = 个人承担，橙褐 = 空置；醒目的颜色只留给需要处理的提醒。
export const COLORS = {
  company: '#5470C6',
  companyText: '#34489A',
  personal: '#E3B26B',
  personalText: '#8A5A1C',
  vacant: '#D98C4A',
  vacantText: '#9A5A1F',
  guest: '#8C96A8',
  nap: '#C3CAD6',
  empty: '#E6E9EF',
  leaver: '#B42318',
};

export const STATUS_ORDER = ['入住', '空置', '客房', '午休室'];

export const STATUS_STYLE = {
  入住: { text: '#34489A', dot: COLORS.company, line: 'solid' },
  空置: { text: '#9A5A1F', dot: COLORS.vacant, line: 'solid' },
  客房: { text: '#4A5263', dot: COLORS.guest, line: 'solid' },
  午休室: { text: '#5B6475', dot: COLORS.nap, line: 'dashed' },
};

const USE_COLORS = { 员工: COLORS.company, 空: COLORS.vacant, 午休室: COLORS.guest, 客房: COLORS.nap };

export function money(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function whole(value) {
  return Math.round(Number(value || 0)).toLocaleString('zh-CN');
}

export function percent(part, total, digits = 1) {
  const base = Number(total || 0);
  if (!base) return '0%';
  return `${Number(((Number(part || 0) / base) * 100).toFixed(digits))}%`;
}

export function ratioWidth(part, total) {
  const base = Number(total || 0);
  if (!base) return '0%';
  return `${Math.max(0, Math.min(100, (Number(part || 0) / base) * 100)).toFixed(1)}%`;
}

export function monthLabel(period) {
  return `${Number(String(period || '').slice(5, 7))} 月`;
}

export function monthTitle(period) {
  const [year, month] = String(period || '').split('-');
  return `${year} 年 ${Number(month)} 月`;
}

export function dayLabel(isoDate) {
  const [, month, day] = String(isoDate || '').split('-');
  return `${Number(month)} 月 ${Number(day)} 日`;
}

function addDays(isoDate, days) {
  const [year, month, day] = String(isoDate).split('-').map(Number);
  const value = new Date(Date.UTC(year, month - 1, day + days));
  return value.toISOString().slice(0, 10);
}

// 入住情况环形图：入住 / 空置 / 客房 / 午休室 按房间数占比。
export function donutGradient(occupancy) {
  const total = Number(occupancy?.total || 0);
  if (!total) return `conic-gradient(${COLORS.empty} 0deg 360deg)`;
  let start = 0;
  const parts = STATUS_ORDER.map((status) => {
    const end = start + (Number(occupancy[status] || 0) / total) * 360;
    const part = `${STATUS_STYLE[status].dot} ${start.toFixed(1)}deg ${end.toFixed(1)}deg`;
    start = end;
    return part;
  });
  return `conic-gradient(${parts.join(', ')})`;
}

// 顶部租约提醒：到期日相同就合成一句；提前 7 天定下续租/退租。
export function leaseMessage(alert, totalRooms) {
  if (!alert) return null;
  const parts = [];
  if (alert.count) {
    const everyRoom = alert.count === totalRooms ? '都' : '';
    parts.push(alert.same_date
      ? `${alert.count} 间房的租约${everyRoom}在 ${alert.earliest_date} 到期，还剩 ${alert.days_left} 天。`
      : `${alert.count} 间房的租约在 60 天内到期，最早 ${alert.earliest_date}（还剩 ${alert.days_left} 天）。`);
  }
  if (alert.expired_count) parts.push(`另有 ${alert.expired_count} 间房的租约已过期。`);
  const detail = alert.count && alert.days_left > 7
    ? `需要续租、退租的房间请在 ${dayLabel(addDays(alert.earliest_date, -7))}前定下来。`
    : '请尽快确定续租或退租。';
  return { title: parts.join(''), detail };
}

export function leaseText(room) {
  if (!room?.lease_end_date) return '未填写到期日';
  const days = room.lease_days_left;
  if (days < 0) return `${room.lease_end_date} 已到期`;
  return `${room.lease_end_date} 到期（剩 ${days} 天）`;
}

export function useRows(cost) {
  const total = Number(cost?.company || 0);
  return (cost?.uses || []).map((use) => ({
    ...use,
    color: USE_COLORS[use.key] || COLORS.nap,
    text: use.count ? `${use.label}（${use.count} ${use.unit}）` : use.label,
    share: percent(use.amount, total, 0),
    width: ratioWidth(use.amount, total),
  }));
}

export function subjectRows(cost) {
  const total = Number(cost?.company || 0);
  const largest = Math.max(0, ...(cost?.subjects || []).map((subject) => Number(subject.amount || 0)));
  return (cost?.subjects || []).map((subject) => ({
    ...subject,
    share: percent(subject.amount, total, 0),
    width: ratioWidth(subject.amount, largest),
  }));
}

export function roomNote(room) {
  if (!room) return '';
  if (room.status === '空置') return '空置期间房租和水电都由公司承担。';
  if (room.status === '客房' || room.status === '午休室') return `${room.status}是功能用房，费用全部由公司承担。`;
  if (!room.total) return '所选月份还没有登记这间房的费用。';
  return `个人承担 ${percent(room.personal, room.total, 0)}，公司承担 ${percent(room.company, room.total, 0)}。`;
}

export function groupByBuilding(rooms) {
  const groups = new Map();
  for (const room of rooms || []) {
    if (!groups.has(room.building)) groups.set(room.building, []);
    groups.get(room.building).push(room);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === '其他') - (b === '其他') || a.localeCompare(b))
    .map(([name, list]) => ({
      name,
      rooms: list,
      summary: `${list.length} 间 · 入住 ${list.filter((room) => room.status === '入住').length} · 空置 ${list.filter((room) => room.status === '空置').length}`,
    }));
}

// 每月费用柱：按最高一个月的总额等比缩放；未登记的月份画虚线框。
export function trendBars(trend, height = 160) {
  const largest = Math.max(0, ...(trend || []).map((month) => Number(month.total || 0)));
  return (trend || []).map((month) => ({
    ...month,
    label: monthLabel(month.period),
    companyHeight: largest ? Math.round((month.company / largest) * height) : 0,
    personalHeight: largest ? Math.round((month.personal / largest) * height) : 0,
  }));
}

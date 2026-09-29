//! Быстрые расчёты GenshinMap на Rust.
//!
//! `astar` — поиск пути по сетке стоимостей, точная копия `NavGrid._astar_py`
//! из `backend/maps/navigation.py`: те же шаги, стоимости, эвристика и порядок
//! в очереди `(f, d, y, x)`, поэтому путь совпадает с Python-версией клетка в клетку.
//! Модуль необязательный: без него приложение считает то же самое на Python.

use std::cmp::Ordering;
use std::collections::BinaryHeap;

const STEPS: [(i64, i64, f64); 8] = [
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, 1.414),
    (-1, 1, 1.414),
    (1, -1, 1.414),
    (1, 1, 1.414),
];

/// Элемент очереди. BinaryHeap — max-куча, поэтому сравнение перевёрнуто:
/// сверху оказывается наименьший (f, d, y, x) — как у heapq в Python.
struct Node {
    f: f64,
    d: f64,
    y: i64,
    x: i64,
}

impl PartialEq for Node {
    fn eq(&self, o: &Self) -> bool {
        self.cmp(o) == Ordering::Equal
    }
}
impl Eq for Node {}
impl PartialOrd for Node {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Node {
    fn cmp(&self, o: &Self) -> Ordering {
        o.f.total_cmp(&self.f)
            .then_with(|| o.d.total_cmp(&self.d))
            .then_with(|| o.y.cmp(&self.y))
            .then_with(|| o.x.cmp(&self.x))
    }
}

/// A* по сетке `cost` (h×w, построчно). Непроходимые клетки — не конечные числа.
/// Возвращает клетки (y, x) от старта до цели или пустой список.
pub fn astar_grid(
    cost: &[f32],
    h: usize,
    w: usize,
    s: (i64, i64),
    g: (i64, i64),
    hmin: f64,
    edge_goal_cost: f64,
) -> Vec<(i64, i64)> {
    let (hh, ww) = (h as i64, w as i64);
    let inside = |y: i64, x: i64| y >= 0 && y < hh && x >= 0 && x < ww;
    if cost.len() != h * w || !inside(s.0, s.1) || !inside(g.0, g.1) {
        return Vec::new();
    }
    let idx = |y: i64, x: i64| (y * ww + x) as usize;
    let heur = |y: i64, x: i64| ((y - g.0) as f64).hypot((x - g.1) as f64) * hmin;
    // старт на проходимой клетке — тогда к непроходимой цели не пускаем
    let start_ok = (cost[idx(s.0, s.1)] as f64).is_finite();

    let mut best = vec![f64::INFINITY; h * w];
    let mut came = vec![usize::MAX; h * w];
    let mut heap = BinaryHeap::new();
    best[idx(s.0, s.1)] = 0.0;
    heap.push(Node { f: heur(s.0, s.1), d: 0.0, y: s.0, x: s.1 });

    while let Some(Node { d, y, x, .. }) = heap.pop() {
        if (y, x) == g {
            let mut out = vec![(y, x)];
            let mut cur = idx(y, x);
            while came[cur] != usize::MAX {
                cur = came[cur];
                out.push(((cur / w) as i64, (cur % w) as i64));
            }
            out.reverse();
            return out;
        }
        if d > best[idx(y, x)] {
            continue;
        }
        for &(dy, dx, m) in STEPS.iter() {
            let (ny, nx) = (y + dy, x + dx);
            if !inside(ny, nx) {
                continue;
            }
            let mut c = cost[idx(ny, nx)] as f64;
            if !c.is_finite() {
                if start_ok || (ny, nx) != g {
                    continue;
                }
                c = edge_goal_cost; // цель у самого края — пускаем
            }
            let nd = d + m * c;
            let ni = idx(ny, nx);
            if nd < best[ni] {
                best[ni] = nd;
                came[ni] = idx(y, x);
                heap.push(Node { f: nd + heur(ny, nx), d: nd, y: ny, x: nx });
            }
        }
    }
    Vec::new()
}

#[cfg(feature = "python")]
mod py {
    use pyo3::prelude::*;

    /// astar(cost_bytes, h, w, start, goal, hmin, edge_goal_cost) -> [(y, x), ...]
    ///
    /// cost_bytes — сетка float32 построчно (numpy: arr.astype(np.float32).tobytes()).
    #[pyfunction]
    fn astar(
        py: Python<'_>,
        cost_bytes: &[u8],
        h: usize,
        w: usize,
        start: (i64, i64),
        goal: (i64, i64),
        hmin: f64,
        edge_goal_cost: f64,
    ) -> PyResult<Vec<(i64, i64)>> {
        if cost_bytes.len() != h * w * 4 {
            return Err(pyo3::exceptions::PyValueError::new_err("cost_bytes: ожидается h*w*4 байт"));
        }
        let cost: Vec<f32> = cost_bytes
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
            .collect();
        // пока ищем путь, GIL свободен — окно и распознавание не ждут
        Ok(py.allow_threads(|| super::astar_grid(&cost, h, w, start, goal, hmin, edge_goal_cost)))
    }

    #[pymodule]
    fn genshinmap_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(astar, m)?)?;
        m.add("__version__", env!("CARGO_PKG_VERSION"))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn goes_around_wall() {
        // стена в столбце 5 с проходом в строке 0
        let (h, w) = (6usize, 10usize);
        let mut cost = vec![1.0f32; h * w];
        for y in 1..h {
            cost[y * w + 5] = f32::INFINITY;
        }
        let p = astar_grid(&cost, h, w, (5, 0), (5, 9), 0.45, 1.0);
        assert_eq!(p.first(), Some(&(5, 0)));
        assert_eq!(p.last(), Some(&(5, 9)));
        assert!(p.iter().all(|&(y, x)| cost[(y as usize) * w + x as usize].is_finite()));
        assert!(p.contains(&(0, 5)));
    }

    #[test]
    fn unreachable_is_empty() {
        let (h, w) = (3usize, 3usize);
        let mut cost = vec![1.0f32; h * w];
        for y in 0..h {
            cost[y * w + 1] = f32::INFINITY;
        }
        assert!(astar_grid(&cost, h, w, (1, 0), (1, 2), 0.45, 1.0).is_empty());
    }
}

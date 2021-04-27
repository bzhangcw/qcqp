# branch and bound tree implementations
import json
import time
from dataclasses import dataclass
from queue import PriorityQueue

import numpy as np
from . import bg_msk, bg_cvx
from .classes import QP, Params, qp_obj_func, Result


class BCParams(Params):
    feas_eps = 1e-5
    opt_eps = 5e-4
    time_limit = 200
    backend_name = 'cvx'
    sdp_solver = 'MOSEK'


class Branch(object):
    def __init__(self):
        self.xpivot = None
        self.xpivot_val = None
        self.xminor = None
        self.xminor_val = None
        self.ypivot = None
        self.ypivot_val = None

    def simple_vio_branch(self, x, y, res):
        res_sum = res.sum(0)
        x_index = res_sum.argmax()
        self.xpivot = x_index
        self.xpivot_val = x[self.xpivot, 0].round(6)
        x_minor = res[x_index].argmax()
        self.xminor = x_minor
        self.xminor_val = x[x_minor, 0].round(6)
        self.ypivot = x_index, x_minor
        self.ypivot_val = y[x_index, x_minor].round(6)


class Bounds(object):
    def __init__(self, xlb=None, xub=None, ylb=None, yub=None):
        # sparse implementation
        self.xlb = xlb.copy()
        self.xub = xub.copy()
        self.ylb = ylb.copy()
        self.yub = yub.copy()

    def unpack(self):
        return self.xlb, self.xub, self.ylb, self.yub

    def update_bounds_from_branch(self, branch: Branch, left=True):
        # todo, extend this
        _succeed = False
        _pivot = branch.xpivot
        _val = branch.xpivot_val
        _lb, _ub = self.xlb[_pivot, 0], self.xub[_pivot, 0]
        if left and _val < _ub:
            # <= and a valid upper bound
            self.xub[_pivot, 0] = _val
            _succeed = True
        if not left and _val > _lb:
            self.xlb[_pivot, 0] = _val
            # self.ylb = self.xlb @ self.xlb.T
            _succeed = True

        # after update, check bound feasibility:
        if self.xlb[_pivot, 0] > self.xub[_pivot, 0]:
            _succeed = False
        return _succeed


class CuttingPlane(object):
    def __init__(self, data):
        self.data = data

    def serialize_to_cvx(self, *args, **kwargs):
        pass

    def serialize_to_msk(self, *args, **kwargs):
        pass

    def serialize(self, backend_name, *args, **kwargs):
        if backend_name == 'cvx':
            self.serialize_to_cvx(*args, **kwargs)
        elif backend_name == 'msk':
            self.serialize_to_msk(*args, **kwargs)
        else:
            raise ValueError(f"not implemented backend {backend_name}")


class RLTCuttingPlane(CuttingPlane):
    def __init__(self, data):
        super().__init__(data)

    def serialize_to_cvx(self, xvar, yvar):
        i, j, u_i, l_i, u_j, l_j = self.data
        # (xi - li)(xj - uj) <= 0
        expr1 = yvar[i, j] - xvar[i, 0] * u_j - l_i * xvar[j, 0] + u_j * l_i <= 0
        # (xi - ui)(xj - lj) <= 0
        expr2 = yvar[i, j] - xvar[i, 0] * l_j - u_i * xvar[j, 0] + u_i * l_j <= 0
        # (xi - li)(xj - lj) >= 0
        expr3 = yvar[i, j] - xvar[i, 0] * l_j - l_i * xvar[j, 0] + l_j * l_i >= 0
        # (xi - ui)(xj - uj) >= 0
        expr4 = yvar[i, j] - xvar[i, 0] * u_j - u_i * xvar[j, 0] + u_i * u_j >= 0
        yield expr1
        yield expr2
        yield expr3
        yield expr4

    def serialize_to_msk(self, xvar, yvar, zvar):
        expr = bg_msk.expr
        exprs = expr.sub
        exprm = expr.mul
        n = yvar.getShape()[0]
        i, j, u_i, l_i, u_j, l_j = self.data
        yij = zvar.index(i, j)
        xi, xj = zvar.index(n, i), zvar.index(n, j)
        # (xi - li)(xj - uj) <= 0
        expr1, dom1 = exprs(exprs(yij, exprm(u_j, xi)),
                            exprm(l_i, xj)), bg_msk.dom.lessThan(- u_j * l_i)
        # (xi - ui)(xj - lj) <= 0
        expr2, dom2 = exprs(exprs(yij, exprm(l_j, xi)),
                            exprm(u_i, xj)), bg_msk.dom.lessThan(- u_i * l_j)
        # (xi - li)(xj - lj) >= 0
        expr3, dom3 = exprs(exprs(yij, exprm(l_j, xi)),
                            exprm(l_i, xj)), bg_msk.dom.greaterThan(- l_j * l_i)
        # (xi - ui)(xj - uj) >= 0
        expr4, dom4 = exprs(exprs(yij, exprm(u_j, xi)),
                            exprm(u_i, xj)), bg_msk.dom.greaterThan(-u_i * u_j)
        yield expr1, dom1
        yield expr2, dom2
        yield expr3, dom3
        yield expr4, dom4


def add_rlt_cuts(branch, bounds):
    i = branch.xpivot
    j = branch.xminor
    u_i, l_i = bounds.xub[i, 0], bounds.xlb[i, 0]
    u_j, l_j = bounds.xub[j, 0], bounds.xlb[j, 0]
    return RLTCuttingPlane((i, j, u_i, l_i, u_j, l_j))


cutting_method = {
    'rlt': add_rlt_cuts
}


class Cuts(object):

    def __init__(self):
        self.cuts = {}

    def generate_cuts(self, branch: Branch, bounds: Bounds, scope=None):

        # cuts
        if scope is None:
            scope = cutting_method
        new_cuts = Cuts()
        for k, v in scope.items():
            val = v(branch, bounds)
            new_cuts.cuts[k] = self.cuts.get(k, []) + [val]

        return new_cuts

    def add_cuts(self, r: Result, backend_name):
        if backend_name == 'cvx':
            assert isinstance(r, bg_cvx.CVXResult)
            self.add_cuts_to_cvx(r)
        elif backend_name == 'msk':
            assert isinstance(r, bg_msk.MSKResult)
            self.add_cuts_to_msk(r)
        else:
            raise ValueError(f"not implemented backend {backend_name}")

    def add_cuts_to_cvx(self, r: bg_cvx.CVXResult):

        _problem = r.problem
        x, y = r.xvar, r.yvar

        for cut_type, cut_list in self.cuts.items():
            for ct in cut_list:
                for expr in ct.serialize_to_cvx(x, y):
                    _problem._constraints.append(expr)

    def add_cuts_to_msk(self, r: bg_msk.MSKResult):

        _problem: bg_msk.mf.Model = r.problem
        x, y, z = r.xvar, r.yvar, r.zvar

        for cut_type, cut_list in self.cuts.items():
            for ct in cut_list:
                for expr, dom in ct.serialize_to_msk(x, y, z):
                    _problem.constraint(expr, dom)


@dataclass(order=True)
class BBItem(object):
    def __init__(self, qp, depth, node_id, parent_id, result, bound: Bounds, cuts: Cuts):
        self.priority = 0
        self.depth = depth
        self.node_id = node_id
        self.parent_id = parent_id
        self.result = result
        self.qp = qp
        self.cuts = cuts
        if bound is None:
            self.bound = Bounds()
        else:
            self.bound = bound


def generate_child_items(total_nodes, parent: BBItem, branch: Branch, verbose=False, backend_name='msk',
                         backend_func=None, sdp_solver="MOSEK"):
    Q, q, A, a, b, sign, lb, ub, ylb, yub, diagx = parent.qp.unpack()
    # left <=
    left_bounds = Bounds(*parent.bound.unpack())
    left_succ = left_bounds.update_bounds_from_branch(branch, left=True)
    left_qp = QP(
        Q, q, A, a, b, sign,
        *left_bounds.unpack()
    )
    left_r = backend_func(*left_qp.unpack(), solver=sdp_solver, verbose=verbose, solve=False)
    if not left_succ:
        # problem is infeasible:
        left_r.solved = True
        left_r.relax_obj = -1e6
        left_cuts = Cuts()
    else:
        # add cuts to cut off
        left_cuts = parent.cuts.generate_cuts(branch, left_bounds)
        left_cuts.add_cuts(left_r, backend_name)

    left_item = BBItem(left_qp, parent.depth + 1, total_nodes, parent.node_id, left_r, left_bounds, left_cuts)

    # right >=
    right_bounds = Bounds(*parent.bound.unpack())
    right_succ = right_bounds.update_bounds_from_branch(branch, left=False)
    right_qp = QP(
        Q, q, A, a, b, sign,
        *right_bounds.unpack()
    )
    right_r = backend_func(*right_qp.unpack(), solver=sdp_solver, verbose=verbose, solve=False)
    if not right_succ:
        # problem is infeasible
        right_r.solved = True
        right_r.relax_obj = -1e6
        right_cuts = Cuts()
    else:
        # add cuts to cut off
        right_cuts = parent.cuts.generate_cuts(branch, right_bounds)
        right_cuts.add_cuts(right_r, backend_name)

    right_item = BBItem(right_qp, parent.depth + 1, total_nodes + 1, parent.node_id, right_r, right_bounds, right_cuts)
    return left_item, right_item


def bb_box(qp: QP, verbose=False, params=BCParams()):
    print(json.dumps(params.__dict__(), indent=2))
    backend_name = params.backend_name
    if backend_name == 'msk':
        backend_func = bg_msk.shor_relaxation
    elif backend_name == 'cvx':
        backend_func = bg_cvx.shor_relaxation
    else:
        raise ValueError("not implemented")
    # choose branching

    # problems
    k = 0
    start_time = time.time()
    print("solving root node")
    root_r = backend_func(*qp.unpack(), solver=params.sdp_solver, verbose=True, solve=True)
    best_r = root_r
    # root
    root_bound = Bounds(
        qp.lb, qp.ub,
        qp.ylb, qp.yub
    )
    # global cuts
    glc = Cuts()

    root = BBItem(qp, 0, 0, -1, result=root_r, bound=root_bound, cuts=glc)
    total_nodes = 1
    ub = root_r.relax_obj
    lb = -1e6

    queue = PriorityQueue()
    queue.put((-ub, root))
    feasible = {}

    while not queue.empty():
        priority, item = queue.get()
        r = item.result

        parent_sdp_val = - priority

        if parent_sdp_val < lb:
            # prune this tree
            print(f"prune #{item.node_id} since parent pruned")
            continue

        if not r.solved:
            r.solve()
            r.true_obj = qp_obj_func(item.qp.Q, item.qp.q, r.xval)
            r.solve_time = time.time() - start_time

        if r.relax_obj < lb:
            # prune this tree
            print(f"prune #{item.node_id} by bound")
            continue

        ub = min(parent_sdp_val, ub)
        r.bound = ub
        if r.true_obj > lb:
            best_r = r
            lb = r.true_obj

        gap = (ub - lb) / lb

        x = r.xval
        y = r.yval
        res = np.abs(y - x @ x.T)

        print(
            f"time: {r.solve_time: .2f} #{item.node_id}, "
            f"depth: {item.depth}, feas: {res.max():.3e}, obj: {r.true_obj:.4f}, "
            f"sdp_obj: {r.relax_obj:.4f}, gap:{gap:.4%} ([{lb: .2f},{ub: .2f}]")

        if gap <= params.opt_eps or r.solve_time >= params.time_limit:
            print(f"terminate #{item.node_id} by gap or time_limit")
            break

        if res.max() <= params.feas_eps:
            print(f"prune #{item.node_id} by feasible solution")
            feasible[item.node_id] = r
            continue

        ## branching

        br = Branch()
        br.simple_vio_branch(x, y, res)
        left_item, right_item = generate_child_items(
            total_nodes, item, br, sdp_solver=params.sdp_solver, verbose=verbose, backend_name=backend_name,
            backend_func=backend_func)
        total_nodes += 2
        next_priority = - r.relax_obj.round(3)
        queue.put((next_priority, right_item))
        queue.put((next_priority, left_item))
        #

        k += 1

    best_r.solve_time = time.time() - start_time
    return best_r

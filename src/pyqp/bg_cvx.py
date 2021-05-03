import cvxpy as cvx
import numpy as np
from .classes import Result, qp_obj_func, QP, MscBounds


class CVXResult(Result):
    def __init__(self, problem=None, yval=0, xval=0, tval=0, relax_obj=0, true_obj=0, bound=0, solve_time=0, xvar=None,
                 yvar=None):
        super().__init__(problem, yval, xval, tval, relax_obj, true_obj, bound, solve_time)
        self.xvar = xvar
        self.yvar = yvar
        self.solved = False

    def solve(self):
        self.problem.solve()
        self.yval = self.yvar.value
        self.xval = self.xvar.value
        self.relax_obj = self.problem.value
        self.solved = True


class CVXMscResult(CVXResult):
    def __init__(self, problem=None, yval=0, xval=0, tval=0, relax_obj=0, true_obj=0, bound=0, solve_time=0, xvar=None,
                 yvar=None):
        super().__init__(problem, yval, xval, tval, relax_obj, true_obj, bound, solve_time, xvar, yvar)
        self.zvar = None
        self.zval = None
        self.Zvar = None
        self.Yvar = None
        self.Yval = None
        self.Zval = None
        self.solved = False

    def solve(self, verbose=True):
        try:
            self.problem.solve(verbose=verbose, solver='MOSEK')
            status = self.problem.status
        except cvx.error.SolverError as e:
            status = 'failed'
        if status == 'optimal':
            self.xval = self.xvar.value.round(4)
            self.yval = self.yvar.value.round(4)
            self.zval = self.zvar.value.round(4)
            self.Yval = np.hstack([xx.value.round(4) for xx in self.Yvar])
            self.Zval = np.hstack([xx.value.round(4) for xx in self.Zvar])
            self.relax_obj = self.problem.value
        else: # infeasible
            self.relax_obj = 1e-6
        self.solved = True


def cvx_sdp(*params, sense="max", rel_type=1, **kwargs):
    Q, q, A, a, b, sign, lb, ub = params

    if rel_type == 1:
        _ = shor_relaxation(Q, q, A, a, b, sign, lb, ub, sense="max", **kwargs)
    elif rel_type == 2:
        _ = compact_relaxation(Q, q, A, a, b, sign, lb, ub, sense="max", **kwargs)
    else:
        raise ValueError("no such SDP defined")
    return _


def shor_relaxation(Q, q, A, a, b, sign,
                    lb, ub,
                    ylb=None, yub=None,
                    diagx=None,
                    solver="SCS", sense="max", verbose=True, solve=True, **kwargs):
    """
    use a Y along with x in the SDP
        for basic 0 <= x <= e, diag(Y) <= x
    Parameters
    ----------
    Q
    q
    A
    a
    b
    sign
    lb
    ub
    solver
    sense
    kwargs

    Returns
    -------

    """
    _unused = kwargs
    m, n, d = a.shape
    xshape = (n, d)

    Y = cvx.Variable((n, n), PSD=True)
    x = cvx.Variable(xshape)

    # bounds
    constrs = [x <= ub, x >= lb]
    if ylb is not None:
        constrs += [Y >= ylb]
    if yub is not None:
        constrs += [Y <= yub]
    constrs += [cvx.bmat([[np.eye(d), x.T], [x, Y]]) >> 0]
    constrs += [cvx.diag(Y) <= x[:, 0]]
    for i in range(m):
        if sign[i] == 0:
            constrs += [cvx.trace(A[i].T @ Y) + cvx.trace(a[i].T @ x) == b[i]]
        elif sign[i] == -1:
            constrs += [cvx.trace(A[i].T @ Y) + cvx.trace(a[i].T @ x) >= b[i]]
        else:
            constrs += [cvx.trace(A[i].T @ Y) + cvx.trace(a[i].T @ x) <= b[i]]

    # objectives
    obj_expr = cvx.trace(Q @ Y) + cvx.trace(q.T @ x)
    obj_expr_cp = cvx.Maximize(obj_expr) if sense == 'max' else cvx.Minimize(
        obj_expr)

    r = CVXResult()
    r.xvar = x
    r.yvar = Y
    problem = cvx.Problem(objective=obj_expr_cp, constraints=constrs)
    r.problem = problem
    if not solve:
        return r

    problem.solve(verbose=verbose, solver=solver)
    xval = x.value
    r.yval = Y.value
    r.xval = xval
    r.relax_obj = problem.value
    r.true_obj = qp_obj_func(Q, q, xval)
    r.solved = True
    return r


def srlt_relaxation(Q, q, A, a, b, sign,
                    lb, ub,
                    ylb=None, yub=None,
                    solver="MOSEK", sense="max", verbose=True, solve=True, **kwargs):
    """
    use a Y along with x in the SDP
        for basic 0 <= x <= e, diag(Y) = x
    Parameters
    ----------
    Q
    q
    A
    a
    b
    sign
    lb
    ub
    solver
    sense
    kwargs

    Returns
    -------

    """
    _unused = kwargs
    m, n, d = a.shape
    xshape = (n, d)

    Y = cvx.Variable((n, n), PSD=True)
    x = cvx.Variable(xshape)

    # bounds
    constrs = [x <= ub, x >= lb]
    constrs += [cvx.bmat([[np.eye(d), x.T], [x, Y]]) >> 0]

    # using srlt
    ones = np.ones(shape=xshape)
    constrs += [Y >= 0]
    constrs += [Y + np.ones(shape=Y.shape) - x @ ones.T - ones @ x.T >= 0]
    constrs += [x @ ones.T - Y >= 0]

    for i in range(m):
        if sign[i] == 0:
            constrs += [cvx.trace(A[i].T @ Y) + cvx.trace(a[i].T @ x) == b[i]]
        elif sign[i] == -1:
            constrs += [cvx.trace(A[i].T @ Y) + cvx.trace(a[i].T @ x) >= b[i]]
        else:
            constrs += [cvx.trace(A[i].T @ Y) + cvx.trace(a[i].T @ x) <= b[i]]

    # objectives
    obj_expr = cvx.trace(Q @ Y) + cvx.trace(q.T @ x)
    obj_expr_cp = cvx.Maximize(obj_expr) if sense == 'max' else cvx.Minimize(
        obj_expr)

    problem = cvx.Problem(objective=obj_expr_cp, constraints=constrs)
    problem.solve(verbose=verbose, solver=solver)
    xval = x.value

    r = CVXResult()
    r.problem = problem
    r.xvar = x
    r.yvar = Y
    r.yval = Y.value
    r.xval = x.value
    r.relax_obj = problem.value
    r.true_obj = qp_obj_func(Q, q, xval)
    return r


def msc_relaxation(qp: QP, bounds: MscBounds = None, solver="MOSEK", sense="max", verbose=True, solve=True, *args,
                   **kwargs):
    """
    The many-small-cone approach
    Returns
    -------
    """
    _unused = kwargs
    Q, q, A, a, b, sign, *_ = qp.unpack()
    if qp.Qpos is None:
        qp.decompose()
    m, n, d = a.shape
    xshape = (n, d)

    x = cvx.Variable(xshape)

    qpos, qipos = qp.Qpos
    qneg, qineg = qp.Qneg

    # declare y+, y-, z+, z-
    y = cvx.Variable(xshape, nonneg=True)
    z = cvx.Variable(xshape)
    Y, Z = [y], [z]
    # bounds
    if bounds is None:
        bounds = MscBounds.construct(qp)
    zlb = bounds.zlb
    zub = bounds.zub
    constrs = [x <= qp.ub, x >= qp.lb]
    constrs += [y <= 1e5 * np.ones((n, n))]

    # For Q in the objective
    # yposub = np.max([(qpos.T @ qp.ub) ** 2, (qpos.T @ qp.lb) ** 2], axis=0)
    # ynegub = np.max([(qneg.T @ qp.ub) ** 2, (qneg.T @ qp.lb) ** 2], axis=0)

    if qipos.shape[0] > 0:
        constrs += [qpos[:, qipos].T @ x == z[qipos, :]]
        # constrs += [y[qipos] <= yposub[qipos]]
    if qineg.shape[0] > 0:
        constrs += [qneg[:, qineg].T @ x == z[qineg, :]]
        # constrs += [y[qineg] <= ynegub[qineg]]
    for idx in range(n):
        _lb, _ub = zlb[0, idx, 0], zub[0, idx, 0]
        constrs += [cvx.bmat([[y[idx], z[idx]], [z[idx], 1]]) >> 0]
        # constrs += [y[idx] - (_lb + _ub) * z[idx] + _lb * _ub <= 0]
        # constrs += [y[idx] - 2 * _lb * z[idx] + _lb ** 2 >= 0]
        # constrs += [y[idx] - 2 * _ub * z[idx] + _ub ** 2 >= 0]

        for i in range(m):
            apos, ipos = qp.Apos[i]
            aneg, ineg = qp.Aneg[i]
            # yposub = np.max([(apos.T @ qp.ub) ** 2, (apos.T @ qp.lb) ** 2], axis=0)
            # ynegub = np.max([(aneg.T @ qp.ub) ** 2, (aneg.T @ qp.lb) ** 2], axis=0)

            if ipos.shape[0] + ineg.shape[0] > 0:
                yi = cvx.Variable(xshape, nonneg=True)
                zi = cvx.Variable(xshape)
                Y.append(yi)
                Z.append(zi)
            else:
                yi = np.zeros(xshape)
                zi = np.zeros(xshape)
            if ipos.shape[0] > 0:
                # means you have positive eigenvalues
                constrs += [apos[:, ipos].T @ x == zi[ipos, :]]
                # constrs += [yi[ipos] <= yposub[ipos]]
            if ineg.shape[0] > 0:
                constrs += [apos[:, ineg].T @ x == zi[ineg, :]]
                # constrs += [yi[ineg] <= ynegub[ineg]]
            for idx in range(n):
                constrs += [cvx.bmat([[yi[idx], zi[idx]], [yi[idx], 1]]) >> 0]

            # y+^Te - y-^Te + q^Tx - b
            expr = cvx.trace(a[i].T @ x) - b[i]
            if ipos.shape[0] > 0:
                expr += cvx.sum(yi[ipos])
            if ineg.shape[0] > 0:
                expr -= cvx.sum(yi[ineg])
            if sign[i] == 0:
                constrs += [expr == 0]
            elif sign[i] == -1:
                constrs += [expr >= 0]
            else:
                constrs += [expr <= 0]

        # objectives
        obj_expr = cvx.sum(y[qipos]) - cvx.sum(y[qineg]) + cvx.trace(q.T @ x)
        obj_expr_cp = cvx.Maximize(obj_expr) if sense == 'max' else cvx.Minimize(
            obj_expr)

        r = CVXMscResult()
        r.xvar = x
        r.yvar = y
        r.zvar = z
        r.Zvar = Z
        r.Yvar = Y

        problem = cvx.Problem(objective=obj_expr_cp, constraints=constrs)
        r.problem = problem
        if not solve:
            return r

        r.solve(verbose=verbose)
        r.true_obj = qp_obj_func(qp.Q, qp.q, r.xval)
        return r

#################
## not used
#################
def compact_relaxation(Q, q, A, a, b, sign, lb, ub, solver="MOSEK", sense="max", verbose=True, **kwargs):
    """
     use a n+1 dimensional PSD matrix Y alone,
        without declare x in the SDP
        for basic -e <= x <= e
    todo 1. check if this work for matrix X
    todo 2. how to handle box constraints?

    Parameters
    ----------
    Q
    q
    A
    a
    b
    sign
    lb
    ub
    solver
    sense
    kwargs

    Returns
    -------

    """
    raise ValueError("to be checked")
    _unused = kwargs
    m, n, d = a.shape
    xshape = (n, d)

    Y = cvx.Variable((n + 1, n + 1), PSD=True)
    _Q = np.bmat([[Q, q / 2], [q.T / 2, np.zeros((1, 1))]])
    constrs = []
    for i in range(m):
        # build block matrix
        _A = np.bmat([[A[i], a[i] / 2], [a[i].T / 2, np.zeros((1, 1))]])
        if sign[i] == 0:
            constrs += [cvx.trace(_A.T @ Y) == b[i]]
        elif sign[i] == -1:
            constrs += [cvx.trace(_A.T @ Y) >= b[i]]
        else:
            constrs += [cvx.trace(_A.T @ Y) <= b[i]]
    # boxes
    _Y_flatten = cvx.diag(Y)
    constrs += [_Y_flatten[:-1] >= lb.flatten(),
                _Y_flatten[:-1] <= ub.flatten(),
                _Y_flatten[-1] >= -1,
                _Y_flatten[-1] <= 1]
    obj_expr = cvx.trace(_Q @ Y)
    obj_expr_cp = cvx.Maximize(obj_expr) if sense == 'max' else cvx.Minimize(
        obj_expr)
    problem = cvx.Problem(objective=obj_expr_cp, constraints=constrs)
    problem.solve(verbose=verbose, solver=solver)
    xtval = np.sqrt(_Y_flatten.value)
    xval = xtval[:-1].reshape(xshape)

    r = CVXResult()
    r.problem = problem
    r.xvar = x
    r.yvar = Y
    r.yval = Y.value
    r.xval = xval
    r.relax_obj = problem.value
    r.true_obj = qp_obj_func(Q, q, xval)
    return r

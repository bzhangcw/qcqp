"""
Using second-order cones, small or large
"""

import numpy as np
import sys
import time

from .bg_msk import MSKResult, dom, expr, mf
from .classes import qp_obj_func, MscBounds, Result, Bounds
from .instances import QP


class MSKMscResult(MSKResult):
  
  def __init__(self):
    super().__init__()
    self.zvar = None
    self.zval = None
    self.Zvar = None
    self.Yvar = None
    self.Yval = 0
    self.Zval = 0
    self.Dvar = None
    self.Dval = None
    self.solved = False
    self.obj_expr = None
    self.qel = None
    self.q = None
  
  def solve(self, verbose=False, qp=None):
    start_time = time.time()
    if verbose:
      self.problem.setLogHandler(sys.stdout)
    try:
      self.problem.solve()
      status = self.problem.getProblemStatus()
    except Exception as e:
      raise ValueError(f"failed with status: {status}")
    end_time = time.time()
    if status == mf.ProblemStatus.PrimalAndDualFeasible:
      self.xval = self.xvar.level().reshape(self.xvar.getShape()).round(self.PRECISION)
      self.zval = self.zvar.level().reshape(self.zvar.getShape()).round(self.PRECISION)
      if self.yvar is not None:
        self.yval = self.yvar.level().reshape(self.yvar.getShape()).round(self.PRECISION)
      self.bound = self.relax_obj = self.problem.primalObjValue()
      if qp is not None:
        self.true_obj = qp_obj_func(qp.Q, qp.q, self.xval)
      ############################
      # extras
      ############################
      yc = self.yval
      zc = self.zval
      resc = self.resc = np.abs(yc - zc ** 2)
      self.resc_feas = resc.max()
      self.resc_feasC = resc[:, 1:].max() if resc.shape[1] > 1 else 0
    else:  # infeasible
      self.bound = self.relax_obj = -1e6
      self.resc_feas = 0
      self.resc_feasC = 0
    self.solved = True
    self.unit_time = self.problem.getSolverDoubleInfo("optimizerTime")
    self.solve_time = round(end_time - start_time, 3)


def msc_diag(
    qp: QP,
    bounds: MscBounds = None,
    sense="max",
    verbose=True,
    solve=True,
    *args,
    **kwargs
):
  """
  The many-small-cone approach (with sdp)
  Returns
  -------
  """
  _unused = kwargs
  Q, q, A, a, b, sign, *_ = qp.unpack()
  
  m, n, dim = a.shape
  xshape = (n, dim)
  model = mf.Model('msc_diagonal_msk')
  
  if verbose:
    model.setLogHandler(sys.stdout)
  
  if bounds is None:
    bounds = MscBounds.construct(qp)
  
  qcones = model.variable("xr", dom.inRotatedQCone(3, n))
  ones = qcones.slice([0, 0], [1, n])
  y = qcones.slice([1, 0], [2, n]).reshape(n, 1)
  z = qcones.slice([2, 0], [3, n]).reshape(n, 1)
  model.constraint(ones, dom.equalsTo(0.5))
  s = model.variable('sqr', [m])
  ##############################
  # or use PSD cone
  # zcone = model.variable("zc", dom.inPSDCone(2, n))
  # y = zcone.slice([0, 0, 0], [n, 1, 1]).reshape([n, 1])
  # z = zcone.slice([0, 0, 1], [n, 1, 2]).reshape([n, 1])
  # for idx in range(n):
  #   model.constraint(zcone.index([idx, 1, 1]), dom.equalsTo(1))
  ##############################
  x = model.variable("x", [*xshape], dom.inRange(bounds.xlb, bounds.xub))
  
  # Q.T x = Z
  model.constraint(expr.sub(expr.mul(qp.U[0], z), x), dom.equalsTo(0))
  
  # RLT cuts
  # this means you can place on x directly.
  rlt_expr = expr.sub(expr.sum(y), expr.dot(bounds.xlb + bounds.xub, x))
  model.constraint(rlt_expr, dom.lessThan(-(bounds.xlb * bounds.xub).sum()))
  # else:
  model.constraint(expr.sum(y), dom.lessThan(bounds.sphere ** 2))
  
  for i in range(m):
    quad_expr = expr.dot(a[i], x)
    Ai = qp.A[i]
    if Ai is not None:
      model.constraint(
        expr.vstack(0.5, s.index(i), expr.flatten(expr.mul(qp.R[i].T, x))),
        dom.inRotatedQCone()
      )
      quad_expr = expr.add(quad_expr, s.index(i))
      quad_expr = expr.sub(quad_expr, expr.dot(qp.l[i] * np.ones((n, 1)), y))
    
    if qp.sign is not None:
      # unilateral case
      quad_dom = dom.equalsTo(b[i]) if sign[i] == 0 else dom.lessThan(b[i])
    
    else:
      # bilateral case
      # todo, fix this
      # quad_dom = dom.inRange(qp.al[i], qp.au[i])
      quad_dom = dom.lessThan(qp.au[i])
    
    model.constraint(quad_expr, quad_dom)
  
  # objectives
  true_obj_expr = expr.add(expr.dot(q, x), expr.dot(qp.gamma[0], y))
  obj_expr = true_obj_expr
  
  # obj_expr = true_obj_expr
  model.objective(
    mf.ObjectiveSense.Minimize
    if sense == 'min' else mf.ObjectiveSense.Maximize, obj_expr
  )
  
  r = MSKMscResult()
  r.obj_expr = true_obj_expr
  r.xvar = x
  r.yvar = y
  r.zvar = z
  r.qel = qp.gamma[0]
  r.q = q
  r.problem = model
  if not solve:
    return r
  
  r.solve(verbose=verbose, qp=qp)
  
  return r

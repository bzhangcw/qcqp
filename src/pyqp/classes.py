try:
    import gurobipy as grb
except:
    print("no gurobipy found!")
    grb = None

import numpy as np


# todo use a C struct or CC class
class QP(object):
    def __init__(self, Q, q, A, a, b, sign, lb, ub, ylb, yub, diagx=None):
        self.Q = Q
        self.q = q
        self.A = A
        self.a = a
        self.b = b
        self.sign = sign
        self.lb = lb
        self.ub = ub
        self.ylb = ylb
        self.yub = yub
        self.diagx = diagx
        self.description = self.__str__()


    def __str__(self):
        # todo add a description
        return ""

    def __repr__(self):
        return self.description

    def unpack(self):
        return self.Q, self.q, self.A, self.a, self.b, self.sign, \
               self.lb, self.ub, self.ylb, self.yub, self.diagx

    @staticmethod
    def create_random_instance(n, m):
        Q = np.random.randint(0, 10, (n, n))
        A = np.random.randint(0, 2, (m, n, n))
        q = np.random.randint(0, 5, (n, 1))
        a = np.random.randint(0, 5, (m, n, 1))
        b = np.random.randint(n, 3 * n, (m))
        sign = np.ones(shape=m)
        lb = np.zeros(shape=(n, 1))
        ub = np.ones(shape=(n, 1))
        return QP(Q, q, A, a, b, sign, lb, ub, lb @ lb.T, ub @ ub.T)


class Eval(object):
    def __init__(self, prob_num, solve_time, best_bound, best_obj, relax_obj=0.0):
        self.prob_num = prob_num
        self.solve_time = round(solve_time, 2)
        self.best_bound = best_bound if best_bound == "-" else round(
            best_bound, 2)
        self.best_obj = round(best_obj, 2)
        self.relax_obj = round(relax_obj, 2)


class Result:
    def __init__(self, problem=None, yval=0, xval=0, tval=0, relax_obj=0, true_obj=0, bound=0,
                 solve_time=0):
        self.problem = problem
        self.yval = yval
        self.xval = xval
        self.tval = tval
        self.relax_obj = relax_obj
        self.true_obj = true_obj
        self.bound = bound
        self.solve_time = solve_time

    def eval(self, problem_id=""):
        return Eval(problem_id, self.solve_time, self.bound, self.true_obj, relax_obj=self.relax_obj)

    def check(self, qp: QP):
        x, y = self.xval, self.yval
        res = (y - x @ x.T)
        print(f"y - xx':{res.min(), res.max()}")
        for m in range(qp.A.shape[0]):
            print(f"A*Y + a * x - b:{(x.T @ qp.A[m] * x).trace() + (qp.a[m].T @ x).trace() - qp.b[m]}")


keys = ['feas_eps', 'opt_eps', 'time_limit']


class Params(object):
    feas_eps = 1e-5
    opt_eps = 1e-4
    time_limit = 200

    def __dict__(self):
        return {k: self.__getattribute__(k) for k in keys}


def qp_obj_func(Q, q, xval: np.ndarray):
    return xval.T.dot(Q).dot(xval).trace() + xval.T.dot(q).trace()

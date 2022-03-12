//
// Created by C. Zhang on 2021/8/2.
//

#include "cut.h"


template<typename BranchType>
std::vector<RLT<BranchType>> RLT<BranchType>::create_from_branch(BranchType &branch, int orient) {
  int i = branch.i;
  int j = branch.j;
  int n = branch.n;
  if (!orient) {
    //left child
    double li = branch.b_left.xlb[i];
    double lj = branch.b_left.xlb[j];
    double ui = branch.b_left.xub[i];
    double uj = branch.b_left.xub[j];
    return {{n, i, j, li, ui, lj, uj},
            {n, j, i, lj, uj, li, ui}};
  }
  double li = branch.b_right.xlb[i];
  double lj = branch.b_right.xlb[j];
  double ui = branch.b_right.xub[i];
  double uj = branch.b_right.xub[j];
  return {{n, i, j, li, ui, lj, uj},
          {n, j, i, lj, uj, li, ui}};
}

template<typename BranchType>
RLT<BranchType>::RLT(int n, int i, int j, double li, double ui, double lj, double uj) {
  int ij = query_index_lt(i, j);
  int jn = query_index_lt(n, j);
  int in = query_index_lt(n, i);
  if (i != j) {
    size = 3;
    index = new int[3]{ij, jn, in};
    vals = new double[3]{1, -0.5 * ui, -0.5 * lj};
  } else {
    size = 2;
    index = new int[2]{ij, jn};
    vals = new double[2]{1, -0.5 * ui - 0.5 * lj};
  }
  b = -lj * ui;

  // @note, only in dbg mode,
  // compute matrix B then use check_solution to see if
  // it is correct.
  using namespace std;
  double *xx = new double[(n + 1) * (n + 2) / 2]{0.0};
  for (int k = 0; k < size; ++k) {
    xx[index[k]] = vals[k];
  }
  double *xm = new double[(n + 1) * (n + 1)];
  input_lower_triangular(xx, xm, n + 1);
  eigen_matmap xem(xm, n + 1, n + 1);
  B = eigen_matrix::Zero(n + 1, n + 1);
  B += xem;
  delete[] xx;
  delete[] xm;
#if QCQP_CUT_DBG
  std::cout << B <<std::endl;
    std::cout << b <<std::endl;
#endif
}

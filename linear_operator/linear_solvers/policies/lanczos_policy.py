from __future__ import annotations

from typing import Optional

import torch

from ...utils.lanczos import lanczos_tridiag, lanczos_tridiag_to_diag
from .linear_solver_policy import LinearSolverPolicy


class NaiveLanczosPolicy(LinearSolverPolicy):
    """Policy choosing approximate eigenvectors as actions."""

    def __init__(self, seeding: float = "random", precond: Optional["LinearOperator"] = None) -> None:
        self.seeding = seeding
        self.precond = precond
        super().__init__()

    def __call__(self, solver_state: "LinearSolverState") -> torch.Tensor:

        if solver_state.iteration == 0:

            # Seed vector
            if self.seeding == "random":
                init_vec = torch.randn(
                    solver_state.problem.A.shape[1],
                    dtype=solver_state.problem.A.dtype,
                    device=solver_state.problem.A.device,
                )
                init_vec = init_vec.div(torch.linalg.vector_norm(init_vec))

            elif self.seeding == "rkhs":
                init_vec = (
                    solver_state.problem.A
                    @ torch.randn(
                        solver_state.problem.A.shape[1],
                        dtype=solver_state.problem.A.dtype,
                        device=solver_state.problem.A.device,
                    )
                    / torch.sqrt(torch.as_tensor(solver_state.problem.A.shape[1]))
                )
            else:
                raise NotImplementedError

            # Cache initial vector
            solver_state.cache["init_vec"] = init_vec

        action = solver_state.cache["init_vec"] - solver_state.problem.A @ solver_state.solution

        if self.precond is not None:
            action = self.precond @ action

        return action


class LanczosPolicy(LinearSolverPolicy):
    """Policy choosing approximate eigenvectors as actions."""

    def __init__(self, descending: bool = True, max_iter: Optional[int] = None) -> None:
        self.descending = descending
        self.max_iter = max_iter
        super().__init__()

    def __call__(self, solver_state: "LinearSolverState") -> torch.Tensor:

        if solver_state.iteration == 0:
            # Compute approximate eigenvectors via Lanczos process

            # Initial seed vector
            init_vecs = solver_state.residual.unsqueeze(-1)
            init_vecs = torch.randn(
                solver_state.problem.A.shape[1],
                1,
                dtype=solver_state.problem.A.dtype,
                device=solver_state.problem.A.device,
            )

            # Lanczos tridiagonalization
            Q, T = lanczos_tridiag(
                solver_state.problem.A.matmul,
                init_vecs=init_vecs,
                max_iter=solver_state.problem.A.shape[1] if self.max_iter is None else self.max_iter,
                dtype=solver_state.problem.A.dtype,
                device=solver_state.problem.A.device,
                matrix_shape=solver_state.problem.A.shape,
                tol=1e-5,
            )
            evals_lanczos, evecs_T = lanczos_tridiag_to_diag(T)
            evecs_lanczos = Q @ evecs_T

            # Cache approximate eigenvectors
            solver_state.cache["evals_lanczos"], idcs = torch.sort(evals_lanczos, descending=self.descending)
            solver_state.cache["evecs_lanczos"] = evecs_lanczos[:, idcs]

            # Cache initial vector
            solver_state.cache["init_vec"] = init_vecs.squeeze(-1).div(torch.linalg.vector_norm(init_vecs))

        # Return approximate eigenvectors according to strategy
        if solver_state.iteration < solver_state.cache["evecs_lanczos"].shape[1]:
            return solver_state.cache["evecs_lanczos"][:, solver_state.iteration]
        else:
            return solver_state.residual

"""Sibson coordinates from independently calculated Voronoi overlaps."""

import numpy as np
import pytest

from Tools.Publication_Maps.natural_neighbor import natural_neighbor_weights


def test_cocircular_grid_cell_uses_all_four_natural_neighbors():
    sites = np.array([[0, 0], [1, 0], [1, 1], [0, 1]])
    query = np.array([[.2, .3], [.5, .5], [.9, .7]])
    x, y = query.T
    expected = np.column_stack(((1 - x) * (1 - y), x * (1 - y), x * y, (1 - x) * y))

    weights = natural_neighbor_weights(sites, query)

    np.testing.assert_allclose(weights.toarray(), expected, atol=1e-14)
    # The choice of Delaunay diagonal may change with input order.
    order = [3, 1, 2, 0]
    permuted = natural_neighbor_weights(sites[order], query)
    np.testing.assert_allclose(permuted.toarray(), expected[:, order], atol=1e-14)


def test_irregular_sites_match_independent_voronoi_intersection_areas():
    sites = np.array([[0, 0], [3, 0], [4, 2], [2, 4], [0, 3], [1.2, 1.4], [2.6, 1.9]])
    query = np.array([[1.8, 1.6], [1.1, .6], [1.6, 2.8], [1.9, .0002]])
    # Each original site's Voronoi polygon was intersected with the new
    # query cell, then divided by the cell area. Last row approaches the hull.
    expected = np.array([
        [0, .0343366952050, 0, .0179353331063, .0070748130359, .5604135459464, .3802396127065],
        [.3763372914464, .1951682809905, 0, 0, 0, .4282788247397, .0002156028234],
        [0, 0, 0, .3715996902568, .1957806350592, .1914360962086, .2411835784755],
        [.3665849917959, .6332742696355, 0, 0, 0, .0001348065606, .0000059320080],
    ])
    weights = natural_neighbor_weights(sites, query)

    np.testing.assert_allclose(weights.toarray(), expected, rtol=0, atol=2e-10)
    np.testing.assert_allclose(weights @ sites, query, rtol=0, atol=2e-11)
    np.testing.assert_allclose(np.asarray(weights.sum(axis=1)), 1., rtol=0, atol=1e-14)
    assert np.all(weights.data >= 0)
    np.testing.assert_allclose(
        natural_neighbor_weights(183 * sites - 280, 183 * query - 280).toarray(), weights.toarray(), atol=2e-12,
    )


def test_exact_electrodes_collinear_boundary_sites_and_unsupported_queries():
    sites = np.array([[0., 0.], [1., 0.], [3., 0.], [2., 1.], [1., 2.]])
    query = np.vstack((sites, [[.4, 0], [2.5, 0], [-.01, 0], [np.nan, 0], [np.inf, 0]]))
    weights = natural_neighbor_weights(sites, query)

    np.testing.assert_array_equal(weights[:5].toarray(), np.eye(5))
    np.testing.assert_allclose(weights[5:7].toarray(), [[.6, .4, 0, 0, 0], [0, .25, .75, 0, 0]], atol=1e-14)
    assert weights[7:].nnz == 0
    assert natural_neighbor_weights(sites, np.empty((0, 2))).shape == (0, len(sites))


def test_invalid_electrode_geometry_is_rejected():
    with pytest.raises(ValueError, match="distinct, finite"):
        natural_neighbor_weights(np.array([[0., 0.], [0., 1.], [0., 0.]]), np.zeros((1, 2)))


def test_camera_queries_reuse_geometry_and_moved_sites_invalidate_it(monkeypatch):
    from Tools.Publication_Maps import natural_neighbor as kernel

    sites = np.array([[0., 0.], [3., 0.], [4., 2.], [.3, 2.], [1.1, 1.2]])
    queries = np.array([[1.2, .6], [.9, 1.4]])
    built = []
    make_cells = kernel._voronoi_cells

    def track_build(coordinates):
        built.append(coordinates.copy())
        return make_cells(coordinates)

    kernel._bounded_voronoi_cells.cache_clear()
    monkeypatch.setattr(kernel, "_voronoi_cells", track_build)
    first = natural_neighbor_weights(sites, queries)
    repeated = natural_neighbor_weights(sites.copy(), queries[::-1])
    np.testing.assert_array_equal(repeated.toarray(), first.toarray()[::-1])
    assert len(built) == 1

    sites[-1] += [.25, .1]
    changed = natural_neighbor_weights(sites, queries)
    assert len(built) == 2
    assert not np.allclose(changed.toarray(), first.toarray())
    np.testing.assert_allclose(changed @ sites, queries, atol=1e-13)


def test_arbitrary_subdivisions_of_an_oblique_hull_edge_remain_supported():
    corners = np.array([[1., -.1], [-.3, -.4], [-1.7, .3]])
    sites = np.vstack([corners, np.array([.5001, .4991, .0008]) @ corners])
    t = np.arange(1, 17) / 17
    query = (1 - t[:, None]) * sites[0] + t[:, None] * sites[1]
    weights = natural_neighbor_weights(sites, query)
    expected = np.column_stack((1 - t, t, np.zeros((len(t), 2))))
    np.testing.assert_allclose(weights.toarray(), expected, atol=1e-13)
    assert natural_neighbor_weights(sites, query + [0, -1e-9]).nnz == 0
